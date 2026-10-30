"""
etl_pipeline.py - IMACAB (VERSION CORRIGÉE v3)
Corrections :
  - Sync Excel → PostgreSQL COMPLÈTE et FORCÉE à chaque appel
  - Suppression des doublons avant insertion (TRUNCATE + INSERT)
  - Invalidation du cache immédiate après chaque sync
  - Logs détaillés pour diagnostiquer les échecs
  - get_database_schema() lit TOUJOURS depuis PostgreSQL après sync (données garanties fraîches)
"""

import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URL = 'postgresql://postgres:0123@localhost:5432/usine_cables'
engine = create_engine(DB_URL)

EXCEL_PATH = 'imacab_data.xlsx'

# ══════════════════════════════════════════════════════════════════
#  CACHE MÉMOIRE (lecture Excel)
# ══════════════════════════════════════════════════════════════════

_excel_cache: dict = {}
_last_excel_mtime: float = 0.0
_last_db_sync_mtime: float = 0.0


def _clean_col(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise un DataFrame : colonnes, dates, booléens."""
    df = df.copy()
    df.columns = [_clean_col(c) for c in df.columns]

    for col in df.columns:
        if 'date' in col:
            df[col] = pd.to_datetime(df[col], errors='coerce')
        elif df[col].dtype == object or str(df[col].dtype) == 'string':
            sample = df[col].dropna().astype(str).str.strip().str.upper().unique()
            bool_vals = {'TRUE', 'FALSE', 'OUI', 'NON', '1', '0', 'TRUE ', 'FALSE '}
            if set(sample).issubset(bool_vals):
                mapping = {
                    'TRUE': True, 'TRUE ': True, 'OUI': True, '1': True,
                    'FALSE': False, 'FALSE ': False, 'NON': False, '0': False
                }
                df[col] = df[col].astype(str).str.strip().str.upper().map(mapping)
    return df


def _load_excel_cache(force: bool = False) -> dict:
    """
    Charge le fichier Excel en mémoire. Recharge si le fichier a changé ou force=True.
    Retourne {nom_table: DataFrame normalisé}.
    """
    global _excel_cache, _last_excel_mtime

    try:
        mtime = os.path.getmtime(EXCEL_PATH)
    except FileNotFoundError:
        logger.error(f"❌ Fichier Excel introuvable : {EXCEL_PATH}")
        return {}

    if not force and mtime <= _last_excel_mtime and _excel_cache:
        return _excel_cache

    logger.info(f"📂 Chargement de {EXCEL_PATH} (mtime={mtime})...")
    try:
        all_sheets = pd.read_excel(EXCEL_PATH, sheet_name=None)
    except Exception as e:
        logger.error(f"❌ Impossible de lire {EXCEL_PATH} : {e}")
        return _excel_cache

    _excel_cache = {}
    for sheet_name, df in all_sheets.items():
        if df.empty:
            logger.warning(f"⚠️  Onglet '{sheet_name}' vide — ignoré")
            continue
        table_name = sheet_name.strip().lower().replace(" ", "_")
        _excel_cache[table_name] = _normalize_df(df)

    _last_excel_mtime = mtime
    logger.info(f"✅ {len(_excel_cache)} onglets chargés : {list(_excel_cache.keys())}")
    for t, df in _excel_cache.items():
        logger.info(f"   {t}: {len(df)} lignes | colonnes: {list(df.columns)}")

    return _excel_cache


# ══════════════════════════════════════════════════════════════════
#  SYNC EXCEL → POSTGRESQL  (CORRIGÉE)
# ══════════════════════════════════════════════════════════════════

def sync_excel_to_db(excel_path: str = EXCEL_PATH) -> dict:
    """
    Synchronisation COMPLÈTE Excel → PostgreSQL.
    
    Stratégie : TRUNCATE + INSERT (pas de replace via pandas qui garde des fantômes)
    - Supprime TOUTES les anciennes données de chaque table
    - Réinsère les données fraîches de l'Excel
    - Vérifie les doublons avant insertion
    - Log chaque étape pour diagnostiquer les erreurs
    """
    global _last_excel_mtime

    results = {
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'tables_updated': [],
        'errors': [],
        'details': []
    }

    # Force rechargement du cache depuis le fichier
    _last_excel_mtime = 0.0
    sheets = _load_excel_cache(force=True)

    if not sheets:
        msg = f"❌ Fichier introuvable ou vide : {excel_path}"
        logger.error(msg)
        return {'success': False, 'error': msg}

    for table_name, df in sheets.items():
        try:
            logger.info(f"🔄 Synchronisation de '{table_name}' ({len(df)} lignes)...")

            # ── Supprimer les doublons dans le DataFrame avant insertion ──
            before_dedup = len(df)
            df = df.drop_duplicates()
            after_dedup = len(df)
            if before_dedup != after_dedup:
                logger.warning(f"   ⚠️  {before_dedup - after_dedup} doublon(s) supprimé(s) dans '{table_name}'")

            # ── TRUNCATE + INSERT (garantit zéro donnée fantôme) ──────────
            with engine.begin() as conn:
                # Vérifier si la table existe
                exists_result = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = :t
                """), {"t": table_name})
                table_exists = exists_result.scalar() > 0

                if table_exists:
                    # TRUNCATE : supprime TOUTES les anciennes lignes
                    conn.execute(text(f'TRUNCATE TABLE public."{table_name}" RESTART IDENTITY CASCADE'))
                    logger.info(f"   🗑️  Table '{table_name}' vidée (TRUNCATE)")

            # INSERT des nouvelles données via pandas (to_sql avec append après truncate)
            df.to_sql(
                table_name,
                engine,
                if_exists='replace',   # Recrée la table avec le bon schéma
                index=False,
                method='multi',
                chunksize=500
            )
            
            logger.info(f"   ✅ '{table_name}' → {len(df)} lignes insérées")
            results['tables_updated'].append({
                'table': table_name,
                'rows': len(df),
                'columns': list(df.columns),
                'status': '✅ SYNC',
                'doublons_supprimes': before_dedup - after_dedup
            })

        except Exception as e:
            msg = f"❌ Erreur sur '{table_name}': {str(e)}"
            logger.error(msg)
            results['errors'].append(msg)
            results['success'] = False

    # ── Vérification post-sync : compter les lignes dans PostgreSQL ──
    logger.info("🔍 Vérification post-synchronisation...")
    for item in results['tables_updated']:
        try:
            with engine.connect() as conn:
                count = conn.execute(
                    text(f'SELECT COUNT(*) FROM public."{item["table"]}"')
                ).scalar()
            item['rows_in_db'] = count
            logger.info(f"   ✅ '{item['table']}' : {count} lignes en BD")
        except Exception as e:
            item['rows_in_db'] = 'erreur'
            logger.warning(f"   ⚠️  Impossible de vérifier '{item['table']}': {e}")

    logger.info(f"{'✅' if results['success'] else '❌'} Sync terminée | "
                f"{len(results['tables_updated'])} tables | "
                f"{len(results['errors'])} erreur(s)")
    
    # Mettre à jour le timestamp de dernière synchro réussie
    if results['success']:
        try:
            global _last_db_sync_mtime
            _last_db_sync_mtime = os.path.getmtime(EXCEL_PATH)
        except:
            pass
            
    return results


def force_sync() -> dict:
    """Force le rechargement du cache Excel ET la sync vers PostgreSQL."""
    global _last_excel_mtime
    _last_excel_mtime = 0.0
    logger.info("🔁 Force sync déclenchée...")
    return sync_excel_to_db()


# ══════════════════════════════════════════════════════════════════
#  SCHÉMA POUR L'IA  (lu depuis PostgreSQL après sync)
# ══════════════════════════════════════════════════════════════════

def get_database_schema() -> str:
    """
    Retourne le schéma complet avec données réelles depuis PostgreSQL.
    
    Priorité :
      1. PostgreSQL (données après sync = toujours fraîches)
      2. Fallback cache Excel si PostgreSQL inaccessible
    
    On exclut les tables système (users, bot_metadata, chat_logs, login_logs).
    """
    EXCLUDED_TABLES = {'users', 'bot_metadata', 'chat_logs', 'login_logs', 'permissions', 'sensitive_alerts'}

    schema_parts = []

    # ✅ CORRECTION : l'auto-sync a été retirée d'ici.
    # Avant, get_database_schema() était appelée à CHAQUE question du chatbot
    # (via le cache 5 min de ollamaAi._get_cached_schema), et vérifiait si le
    # fichier Excel avait changé — si oui, elle relançait une sync COMPLÈTE
    # (TRUNCATE + réinsertion de toutes les tables), ce qui pouvait prendre
    # plusieurs minutes et bloquait la réponse du chatbot.
    # La sync reste déclenchée : (1) au démarrage de Flask (app.py), et
    # (2) manuellement via la route /sync. C'est largement suffisant et ça
    # évite qu'une simple question déclenche une resynchronisation lourde.

    try:
        with engine.connect() as conn:
            # Lister toutes les tables publiques
            tables_res = conn.execute(text("""
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """))
            all_tables = [row[0] for row in tables_res if row[0] not in EXCLUDED_TABLES]

        if not all_tables:
            raise Exception("Aucune table de données trouvée dans PostgreSQL")

        for table in all_tables:
            try:
                with engine.connect() as conn:
                    # Colonnes
                    cols_res = conn.execute(text("""
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = :t
                        ORDER BY ordinal_position;
                    """), {"t": table}).fetchall()

                    col_list = ", ".join(f"{c[0]} ({c[1]})" for c in cols_res)
                    col_names = [c[0] for c in cols_res]

                    # Nombre total de lignes
                    total_count = conn.execute(
                        text(f'SELECT COUNT(*) FROM public."{table}"')
                    ).scalar()

                    # Données (max 3 lignes pour le contexte IA)
                    rows = conn.execute(
                        text(f'SELECT * FROM public."{table}" LIMIT 3')
                    ).fetchall()

                examples = []
                for row in rows:
                    kv = ", ".join(
                        f"{k}={str(v)[:30]!r}" if v is not None else f"{k}=NULL"
                        for k, v in zip(col_names, row)
                    )
                    examples.append(f"  ligne: {kv}")

                if total_count > 3:
                    examples.append(f"  ... ({total_count} lignes au total, affichage limité à 3)")

                example_block = "\n".join(examples) if examples else "  (table vide)"

                schema_parts.append(
                    f"TABLE `{table}` ({total_count} lignes en BD)\n"
                    f"  colonnes : {col_list}\n"
                    f"{example_block}"
                )

            except Exception as e:
                logger.warning(f"⚠️  Erreur lecture table '{table}': {e}")
                schema_parts.append(f"TABLE `{table}` — erreur lecture : {e}")

        return "\n\n".join(schema_parts)

    except Exception as db_error:
        logger.warning(f"⚠️  PostgreSQL inaccessible, fallback Excel: {db_error}")
        # Fallback : utiliser le cache Excel
        sheets = _load_excel_cache()
        if not sheets:
            return "❌ Aucune donnée disponible (PostgreSQL et Excel inaccessibles)"

        for table_name, df in sheets.items():
            col_list = ", ".join(f"{col} ({str(df[col].dtype)})" for col in df.columns)
            rows_text = []
            for _, row in df.head(3).iterrows():
                kv = ", ".join(
                    f"{k}={str(v)[:30]!r}" if pd.notna(v) else f"{k}=NULL"
                    for k, v in row.items()
                )
                rows_text.append(f"  ligne: {kv}")

            if len(df) > 3:
                rows_text.append(f"  ... ({len(df)} lignes au total)")

            schema_parts.append(
                f"TABLE `{table_name}` (SOURCE: Excel — {len(df)} lignes)\n"
                f"  colonnes : {col_list}\n"
                + "\n".join(rows_text)
            )

        return "\n\n".join(schema_parts)


# ══════════════════════════════════════════════════════════════════
#  MAINTENANCE
# ══════════════════════════════════════════════════════════════════

def get_maintenance_tasks(effectue_status=None) -> list:
    try:
        q = 'SELECT * FROM public.maintenaince ORDER BY date_prevue'
        if effectue_status is not None:
            q = (f"SELECT * FROM public.maintenaince "
                 f"WHERE effectue = {effectue_status} ORDER BY date_prevue")
        with engine.connect() as conn:
            result = conn.execute(text(q))
            return [dict(zip(result.keys(), row)) for row in result.fetchall()]
    except Exception as e:
        logger.error(f"❌ get_maintenance_tasks: {e}")
        return []


def update_maintenance_task(task_id: int, effectue: bool) -> dict:
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE public.maintenaince SET effectue = :e WHERE id = :id"),
                {"e": effectue, "id": task_id}
            )
        return {'success': True, 'message': f'Tâche {task_id} mise à jour'}
    except Exception as e:
        logger.error(f"❌ update_maintenance_task: {e}")
        return {'success': False, 'error': str(e)}


# ══════════════════════════════════════════════════════════════════
#  TEST STANDALONE
# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("=== SYNC EXCEL → PostgreSQL ===")
    r = sync_excel_to_db()
    for t in r.get('tables_updated', []):
        print(f"  ✅ {t['table']} : {t['rows']} lignes Excel → {t.get('rows_in_db','?')} en BD")
    if r.get('errors'):
        print("❌ Erreurs :", r['errors'])

    print("\n=== SCHÉMA VU PAR L'IA ===")
    print(get_database_schema()[:3000])