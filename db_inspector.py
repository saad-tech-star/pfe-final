"""
db_inspector.py — IMACAB v3
Module d'inspection automatique de la base PostgreSQL.

Fonctionnalités :
  1. analyze_tables()      → structure + nb lignes + taille de toutes les tables
  2. get_relations()        → clés primaires / étrangères + graphe des relations
  3. detect_nulls()         → colonnes avec NULL + pourcentages
  4. detect_duplicates()    → doublons par table/colonnes avec suggestions

Utilise uniquement psycopg2 (déjà en place dans DataBaseImacab).
SQLAlchemy (déjà dans requirements.txt) utilisé pour la taille des tables.
"""

import logging
from DataBaseImacab import get_connection
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  TABLES SYSTÈME À EXCLURE
# ══════════════════════════════════════════════════════════════════

SYSTEM_SCHEMAS = ('pg_catalog', 'information_schema', 'pg_toast')

# Tables internes IMACAB à ne pas exposer dans les rapports d'inspection
INTERNAL_TABLES = ('users', 'permissions', 'login_logs', 'daily_activity',
                   'bot_metadata', 'chat_logs', 'sensitive_alerts', 'forced_logouts')


def _get_user_tables(cursor, include_internal=False):
    """Retourne la liste des tables utilisateur (schéma public uniquement)."""
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type   = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [r['table_name'] for r in cursor.fetchall()]
    if not include_internal:
        tables = [t for t in tables if t not in INTERNAL_TABLES]
    return tables


# ══════════════════════════════════════════════════════════════════
#  1. ANALYSE DES TABLES
# ══════════════════════════════════════════════════════════════════

def analyze_tables(include_internal=False):
    """
    Retourne pour chaque table :
      - nom, nb_colonnes, colonnes (nom + type), nb_lignes, taille_approx

    Format retour :
    {
      "tables": [
        {
          "nom": "ventes",
          "nb_colonnes": 5,
          "colonnes": [{"nom": "id", "type": "integer"}, ...],
          "nb_lignes": 1240,
          "taille": "128 kB"
        },
        ...
      ],
      "total_tables": 4,
      "total_lignes": 5890
    }
    """
    conn = get_connection()
    if not conn:
        return {"error": "Connexion DB impossible", "tables": []}

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        tables = _get_user_tables(cursor, include_internal)

        result = []
        total_lignes = 0

        for table in tables:
            # ── Colonnes ──────────────────────────────────────────
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = %s
                ORDER BY ordinal_position
            """, (table,))
            colonnes = [
                {"nom": r["column_name"], "type": r["data_type"]}
                for r in cursor.fetchall()
            ]

            # ── Nb lignes (estimation rapide via pg_class) ─────────
            cursor.execute("""
                SELECT reltuples::bigint AS nb_lignes
                FROM pg_class
                WHERE relname = %s
                  AND relnamespace = 'public'::regnamespace
            """, (table,))
            row = cursor.fetchone()
            nb_lignes_est = int(row["nb_lignes"]) if row and row["nb_lignes"] >= 0 else 0

            # Pour les petites tables (< 10 000 lignes), on fait un COUNT exact
            if nb_lignes_est < 10000:
                try:
                    cursor.execute(f'SELECT COUNT(*) AS n FROM public."{table}"')
                    nb_lignes = cursor.fetchone()["n"]
                except Exception:
                    nb_lignes = nb_lignes_est
            else:
                nb_lignes = nb_lignes_est

            total_lignes += nb_lignes

            # ── Taille approximative ──────────────────────────────
            cursor.execute("""
                SELECT pg_size_pretty(pg_total_relation_size(%s)) AS taille
            """, (f'public.{table}',))
            row_size = cursor.fetchone()
            taille = row_size["taille"] if row_size else "?"

            result.append({
                "nom":        table,
                "nb_colonnes": len(colonnes),
                "colonnes":   colonnes,
                "nb_lignes":  nb_lignes,
                "taille":     taille,
            })

        cursor.close()
        conn.close()
        logger.info(f"✅ analyze_tables: {len(result)} tables, {total_lignes} lignes")
        return {
            "tables":        result,
            "total_tables":  len(result),
            "total_lignes":  total_lignes,
        }

    except Exception as e:
        logger.error(f"❌ analyze_tables: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return {"error": str(e), "tables": []}


# ══════════════════════════════════════════════════════════════════
#  2. RELATIONS ENTRE TABLES
# ══════════════════════════════════════════════════════════════════

def get_relations(include_internal=False):
    """
    Détecte les clés primaires et étrangères.
    Retourne :
    {
      "cles_primaires": [{"table": "ventes", "colonne": "id"}, ...],
      "cles_etrangeres": [
        {
          "table_source": "ventes",
          "colonne_source": "client_id",
          "table_cible": "clients",
          "colonne_cible": "id",
          "contrainte": "fk_ventes_client"
        },
        ...
      ],
      "graphe": [
        {"de": "ventes", "vers": "clients", "via": "client_id → id"},
        ...
      ]
    }
    """
    conn = get_connection()
    if not conn:
        return {"error": "Connexion DB impossible"}

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # ── Clés primaires ────────────────────────────────────────
        cursor.execute("""
            SELECT
                tc.table_name  AS "table",
                kcu.column_name AS colonne
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage  AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema    = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema    = 'public'
            ORDER BY tc.table_name, kcu.ordinal_position
        """)
        cles_primaires_raw = cursor.fetchall()

        # ── Clés étrangères ───────────────────────────────────────
        cursor.execute("""
            SELECT
                tc.table_name        AS table_source,
                kcu.column_name      AS colonne_source,
                ccu.table_name       AS table_cible,
                ccu.column_name      AS colonne_cible,
                tc.constraint_name   AS contrainte
            FROM information_schema.table_constraints     AS tc
            JOIN information_schema.key_column_usage      AS kcu
              ON tc.constraint_name  = kcu.constraint_name
             AND tc.table_schema     = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema    = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema    = 'public'
            ORDER BY tc.table_name
        """)
        cles_etrangeres_raw = cursor.fetchall()
        cursor.close()
        conn.close()

        # Filtrer les tables internes si demandé
        excluded = set(INTERNAL_TABLES) if not include_internal else set()

        cles_primaires = [
            {"table": r["table"], "colonne": r["colonne"]}
            for r in cles_primaires_raw
            if r["table"] not in excluded
        ]
        cles_etrangeres = [
            {
                "table_source":   r["table_source"],
                "colonne_source": r["colonne_source"],
                "table_cible":    r["table_cible"],
                "colonne_cible":  r["colonne_cible"],
                "contrainte":     r["contrainte"],
            }
            for r in cles_etrangeres_raw
            if r["table_source"] not in excluded and r["table_cible"] not in excluded
        ]

        graphe = [
            {
                "de":  fk["table_source"],
                "vers": fk["table_cible"],
                "via":  f"{fk['colonne_source']} → {fk['colonne_cible']}",
            }
            for fk in cles_etrangeres
        ]

        logger.info(f"✅ get_relations: {len(cles_primaires)} PK, {len(cles_etrangeres)} FK")
        return {
            "cles_primaires":  cles_primaires,
            "cles_etrangeres": cles_etrangeres,
            "graphe":          graphe,
        }

    except Exception as e:
        logger.error(f"❌ get_relations: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return {"error": str(e)}


def get_relation_between(table_a, table_b):
    """
    Répond à une question du type 'quelle relation entre clients et ventes ?'.
    Retourne une description textuelle + les FK trouvées.
    """
    relations = get_relations(include_internal=True)
    if "error" in relations:
        return relations

    found = []
    for fk in relations["cles_etrangeres"]:
        if (fk["table_source"] == table_a and fk["table_cible"] == table_b) or \
           (fk["table_source"] == table_b and fk["table_cible"] == table_a):
            found.append(fk)

    if not found:
        return {
            "relation_trouvee": False,
            "message": f"Aucune clé étrangère directe trouvée entre '{table_a}' et '{table_b}'.",
            "details": [],
        }

    details = []
    for fk in found:
        details.append(
            f"La table **{fk['table_source']}** référence **{fk['table_cible']}** "
            f"via la colonne `{fk['colonne_source']}` → `{fk['colonne_cible']}` "
            f"(contrainte : {fk['contrainte']})"
        )
    return {
        "relation_trouvee": True,
        "message":          f"{len(found)} relation(s) trouvée(s) entre '{table_a}' et '{table_b}'.",
        "details":          details,
        "fk":               found,
    }


# ══════════════════════════════════════════════════════════════════
#  3. DÉTECTION DES NULL
# ══════════════════════════════════════════════════════════════════

def detect_nulls(tables=None, include_internal=False):
    """
    Scanne toutes les tables (ou celles listées dans `tables`).
    Retourne :
    {
      "rapport": [
        {
          "table": "ventes",
          "colonne": "client_id",
          "nb_null": 45,
          "total_lignes": 1240,
          "pct_null": 3.6
        },
        ...
      ],
      "tables_scannees": 4,
      "colonnes_avec_null": 3,
      "resume": "3 colonnes avec valeurs manquantes sur 4 tables scannées."
    }
    """
    conn = get_connection()
    if not conn:
        return {"error": "Connexion DB impossible", "rapport": []}

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if tables:
            target_tables = tables
        else:
            target_tables = _get_user_tables(cursor, include_internal)

        rapport = []

        for table in target_tables:
            # Récupérer les colonnes nullable
            cursor.execute("""
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = %s
                ORDER BY ordinal_position
            """, (table,))
            colonnes = cursor.fetchall()
            nullable_cols = [c["column_name"] for c in colonnes if c["is_nullable"] == "YES"]

            if not nullable_cols:
                continue

            # Nb total de lignes
            try:
                cursor.execute(f'SELECT COUNT(*) AS n FROM public."{table}"')
                total = cursor.fetchone()["n"]
            except Exception:
                continue

            if total == 0:
                continue

            # COUNT NULL pour chaque colonne nullable en une seule requête
            select_parts = ", ".join(
                f'COUNT(*) FILTER (WHERE "{col}" IS NULL) AS "null_{col}"'
                for col in nullable_cols
            )
            try:
                cursor.execute(f'SELECT {select_parts} FROM public."{table}"')
                null_counts = cursor.fetchone()
            except Exception:
                continue

            for col in nullable_cols:
                nb_null = null_counts.get(f"null_{col}", 0) or 0
                if nb_null > 0:
                    pct = round(nb_null / total * 100, 2)
                    rapport.append({
                        "table":        table,
                        "colonne":      col,
                        "nb_null":      nb_null,
                        "total_lignes": total,
                        "pct_null":     pct,
                    })

        # Trier par pourcentage décroissant
        rapport.sort(key=lambda x: x["pct_null"], reverse=True)

        cursor.close()
        conn.close()

        n_tables  = len(set(r["table"] for r in rapport))
        n_colonnes = len(rapport)
        resume = (
            f"{n_colonnes} colonne(s) avec valeurs manquantes "
            f"dans {n_tables} table(s) sur {len(target_tables)} scannée(s)."
            if n_colonnes > 0
            else f"Aucune valeur NULL détectée dans les {len(target_tables)} table(s) scannée(s). ✅"
        )

        logger.info(f"✅ detect_nulls: {n_colonnes} colonnes NULL")
        return {
            "rapport":              rapport,
            "tables_scannees":      len(target_tables),
            "colonnes_avec_null":   n_colonnes,
            "resume":               resume,
        }

    except Exception as e:
        logger.error(f"❌ detect_nulls: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return {"error": str(e), "rapport": []}


# ══════════════════════════════════════════════════════════════════
#  4. DÉTECTION DES DOUBLONS
# ══════════════════════════════════════════════════════════════════

def detect_duplicates(tables=None, include_internal=False):
    """
    Détecte les doublons dans chaque table en analysant toutes les colonnes
    non-identifiantes (exclut les PK et colonnes timestamp).

    Retourne :
    {
      "rapport": [
        {
          "table": "ventes",
          "colonnes_analysees": ["date_vente", "client_id", "montant"],
          "nb_doublons": 12,
          "nb_groupes": 6,
          "exemples": [...],
          "suggestion": "DELETE FROM ventes WHERE ctid NOT IN (...)"
        },
        ...
      ],
      "tables_avec_doublons": 2,
      "resume": "2 table(s) avec doublons détectés."
    }
    """
    conn = get_connection()
    if not conn:
        return {"error": "Connexion DB impossible", "rapport": []}

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if tables:
            target_tables = tables
        else:
            target_tables = _get_user_tables(cursor, include_internal)

        # Récupérer les PK pour les exclure
        cursor.execute("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage  AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema    = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema    = 'public'
        """)
        pk_map = {}
        for r in cursor.fetchall():
            pk_map.setdefault(r["table_name"], set()).add(r["column_name"])

        rapport = []

        for table in target_tables:
            # Colonnes utilisables (excluant PK et timestamps)
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = %s
                ORDER BY ordinal_position
            """, (table,))
            all_cols = cursor.fetchall()

            pk_cols    = pk_map.get(table, set())
            ts_types   = ('timestamp without time zone', 'timestamp with time zone',
                          'date', 'time without time zone', 'time with time zone')
            # On garde les colonnes "métier" : pas PK, pas auto-générées
            business_cols = [
                c["column_name"] for c in all_cols
                if c["column_name"] not in pk_cols
                and c["data_type"] not in ts_types
                and not c["column_name"].endswith(('_id', '_at', '_date'))
            ]

            # Fallback : si pas de colonnes métier, prendre toutes sauf PK
            if not business_cols:
                business_cols = [
                    c["column_name"] for c in all_cols
                    if c["column_name"] not in pk_cols
                ]

            if len(business_cols) < 2:
                continue

            # Construction de la requête de détection des doublons
            col_list = ", ".join(f'"{c}"' for c in business_cols)
            try:
                cursor.execute(f"""
                    SELECT {col_list}, COUNT(*) AS nb_occurrences
                    FROM public."{table}"
                    GROUP BY {col_list}
                    HAVING COUNT(*) > 1
                    ORDER BY nb_occurrences DESC
                    LIMIT 10
                """)
                doublons = cursor.fetchall()
            except Exception as e:
                logger.warning(f"Skip {table}: {e}")
                continue

            if not doublons:
                continue

            nb_groupes = len(doublons)
            nb_doublons = sum(int(r["nb_occurrences"]) - 1 for r in doublons)

            # Exemples (5 premiers groupes dupliqués)
            exemples = [dict(r) for r in doublons[:5]]

            # Suggestion de nettoyage — version simplifiée (pas de backslash dans f-string)
            cols_simple = ", ".join(business_cols)
            table_quoted = '"' + table + '"'
            suggestion = (
                "-- Conserver uniquement la première occurrence (par ctid) :\n"
                "DELETE FROM public." + table_quoted + "\n"
                "WHERE ctid NOT IN (\n"
                "  SELECT MIN(ctid)\n"
                "  FROM public." + table_quoted + "\n"
                "  GROUP BY " + cols_simple + "\n"
                ");"
            )

            rapport.append({
                "table":              table,
                "colonnes_analysees": business_cols,
                "nb_doublons":        nb_doublons,
                "nb_groupes":         nb_groupes,
                "exemples":           exemples,
                "suggestion":         suggestion,
            })

        cursor.close()
        conn.close()

        n_tables = len(rapport)
        resume = (
            f"{n_tables} table(s) avec doublons détectés. "
            f"Total de {sum(r['nb_doublons'] for r in rapport)} lignes dupliquées."
            if n_tables > 0
            else f"Aucun doublon détecté dans les {len(target_tables)} table(s) analysée(s). ✅"
        )

        logger.info(f"✅ detect_duplicates: {n_tables} tables avec doublons")
        return {
            "rapport":               rapport,
            "tables_avec_doublons":  n_tables,
            "resume":                resume,
        }

    except Exception as e:
        logger.error(f"❌ detect_duplicates: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return {"error": str(e), "rapport": []}


# ══════════════════════════════════════════════════════════════════
#  DÉTECTION D'INTENTION (utilisé par ollamaAi.py)
# ══════════════════════════════════════════════════════════════════

INSPECT_PATTERNS = {
    "analyze_tables": [
        "analyse les tables", "analyser les tables", "analyse la base",
        "analyser la base", "structure de la base", "structure des tables",
        "quelles sont les tables", "liste des tables", "montre les tables",
        "inspecte la base", "inspection de la base", "voir les tables",
        "taille des tables", "combien de lignes", "taille de la base",
        "résumé de la base", "resume de la base",
    ],
    "get_relations": [
        "relation entre", "relations entre", "quelle relation",
        "clé étrangère", "cle etrangere", "clés étrangères", "foreign key",
        "clé primaire", "cle primaire", "relations des tables", "liens entre",
        "graphe des tables", "schéma des relations", "schema des relations",
        "connexions entre tables",
    ],
    "detect_nulls": [
        "valeurs null", "données manquantes", "donnees manquantes",
        "valeurs manquantes", "détecter les null", "detecter les null",
        "colonnes vides", "champs vides", "null dans", "missing values",
        "rapport null", "rapport des null",
    ],
    "detect_duplicates": [
        "doublons", "duplicates", "données dupliquées", "lignes dupliquées",
        "détecter les doublons", "detecter les doublons", "données en double",
        "lignes en double", "nettoyer les doublons", "supprimer les doublons",
        "trouver les doublons",
    ],
}


def detect_inspect_intent(message: str):
    """
    Analyse le message utilisateur et retourne l'action d'inspection détectée.
    Retourne : ('action_name', extras) ou (None, None)
    - extras : dict avec des infos supplémentaires (ex: tables impliquées)
    """
    msg_lower = message.lower()

    for action, patterns in INSPECT_PATTERNS.items():
        if any(p in msg_lower for p in patterns):
            extras = {}

            # Pour get_relations, essayer d'extraire les deux tables mentionnées
            if action == "get_relations":
                # Chercher "entre X et Y"
                import re
                m = re.search(r'entre\s+(\w+)\s+et\s+(\w+)', msg_lower)
                if m:
                    extras["table_a"] = m.group(1)
                    extras["table_b"] = m.group(2)

            return action, extras

    return None, None