import ollama
import json
import re
import time
import etl_pipeline
import DataBaseImacab
import logging
import db_inspector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  CACHE DU SCHÉMA (TTL 5 min) — évite des requêtes DB à chaque message
# ══════════════════════════════════════════════════════════════════
_schema_cache: str = ''
_schema_cache_ts: float = 0.0
SCHEMA_CACHE_TTL = 300  # 5 minutes

def _get_cached_schema() -> str:
    """Retourne le schéma depuis le cache mémoire. Rafraîchit seulement si expiré."""
    global _schema_cache, _schema_cache_ts
    now = time.time()
    if _schema_cache and (now - _schema_cache_ts) < SCHEMA_CACHE_TTL:
        return _schema_cache
    logger.info("🔄 Rafraîchissement du cache schéma...")
    _schema_cache = etl_pipeline.get_database_schema()
    _schema_cache_ts = now
    return _schema_cache


# Mots-clés → tables pertinentes
TABLE_KEYWORDS = {
    'ventes':        ['vente', 'ventes', 'client', 'montant', 'revenu', 'chiffre', 'vendu'],
    'production':    ['production', 'cable', 'vitesse', 'tension', 'fabr'],
    'maintenaince':  ['maintenance', 'panne', 'machine', 'réparation', 'entretien'],
    'suivi_medical': [
        # termes médicaux directs
        'médical', 'medical', 'santé', 'sante', 'infirmerie',
        # actions médicales
        'consultation', 'consulté', 'consulter', 'visité', 'visite',
        'passer chez', 'passé chez', 'passé par', 'vu par',
        'hospitalisé', 'hospitalisation', 'arrêt de travail', 'arrêt maladie',
        'blessure', 'blessé', 'accident de travail', 'diagnostic',
        'traitement', 'prescription', 'médicament', 'medicament',
        'aptitude', 'inapte', 'apte', 'contre-indication',
        # personnes médicales
        'docteur', 'dr.', 'dr ', 'médecin', 'medecin', 'infirmier', 'infirmière',
        'alaoui', 'dr.alaoui', 'dr alaoui',
        'bennis', 'dr.bennis', 'dr bennis',
        'berrad', 'dr.berrad', 'dr berrad',
        # sujets (employés passés en médical)
        'employé', 'employe', 'employés', 'employes',
        'travailleur', 'ouvrier', 'personnel',
        'qui a', 'qui ont', 'combien ont',
        # table directe
        'suivi_medical', 'suivi medical',
    ],
}

def _get_relevant_schema(user_msg: str) -> str:
    """Filtre le schéma pour n'inclure que les tables pertinentes à la question."""
    full_schema = _get_cached_schema()
    msg_lower = user_msg.lower()
    
    relevant_tables = set()
    for table, keywords in TABLE_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            relevant_tables.add(table)
    
    # Si aucune table détectée, retourner le schéma complet
    if not relevant_tables:
        return full_schema
    
    # Filtrer le schéma pour ne garder que les tables pertinentes
    parts = full_schema.split('\n\n')
    filtered = [p for p in parts if any(f'`{t}`' in p for t in relevant_tables)]
    return '\n\n'.join(filtered) if filtered else full_schema

# ══════════════════════════════════════════════════════════════════
#  MATRICE RBAC
# ══════════════════════════════════════════════════════════════════

ROLE_ACCESS = {
    'admin': {
        'description': 'Administrateur système - Accès TOTAL',
        'access_level': 999,
        'tables': ['ALL']
    },
    'directeur': {
        'description': 'Directeur - Accès production/maintenance/ventes',
        'access_level': 3,
        'tables': ['production', 'maintenance', 'ventes', 'users']
    },
    'responsable': {
        'description': 'Responsable - Accès production/maintenance/ventes',
        'access_level': 3,
        'tables': ['production', 'maintenance', 'ventes', 'users']
    },
    'medical': {
        'description': 'Staff Médical - Accès suivi_medical',
        'access_level': 1,
        'tables': ['suivi_medical']
    },
    'operateur': {
        'description': 'Opérateur - Accès production/maintenance',
        'access_level': 2,
        'tables': ['production', 'maintenance']
    }
}

ROLE_ALLOWED_TABLES = {
    'admin':       ['*'],
    'directeur':   ['production', 'maintenance', 'ventes', 'users', 'suivi_medical'],
    'responsable': ['production', 'maintenance', 'ventes', 'users'],
    'medical':     ['suivi_medical'],
    'operateur':   ['production', 'maintenance']
}

# ══════════════════════════════════════════════════════════════════
#  DÉTECTION DU MODE (graphique vs texte)
# ══════════════════════════════════════════════════════════════════

# Mots-clés qui déclenchent le mode GRAPHIQUE
GRAPH_KEYWORDS = [
    'graphe', 'graphique', 'graph', 'chart', 'trace', 'tracé',
    'affiche en graph', 'montre en graph', 'visualise', 'courbe',
    'histogramme', 'camembert', 'diagramme', 'plot', 'visualisation',
    'en courbe', 'en graphe', 'en graphique', 'sous forme graphique',
    'sous forme de graphique', 'affiche sous forme', 'montre sous forme',
    'compare en graph', 'évolution graphique', 'tendance graphique',
    'affiche graphiquement', 'montre graphiquement'
]

# Mots-clés pour le type de graphique
LINE_KEYWORDS  = ['évolution', 'tendance', 'historique', 'line', 'temporel']
PIE_KEYWORDS   = ['camembert', 'répartition', 'proportion', 'pie', 'distribution', 'pourcentage']
BAR_KEYWORDS   = ['compare', 'comparaison', 'barre', 'bar', 'histogramme', 'comparatif', 'vente', 'ventes', 'semaine', 'mois', 'mensuel', 'hebdomadaire']

GREETINGS = [
    'bonjour', 'salut', 'coucou', 'hello', 'hi', 'ça va', 'ca va',
    'merci', 'au revoir', 'bye', 'bonsoir', 'bsr'
]


def _wants_graph(message: str) -> bool:
    """
    Retourne True UNIQUEMENT si l'utilisateur demande explicitement un graphique.
    Une question normale (même sur des données) → False → réponse texte.
    """
    lower = message.lower()
    return any(kw in lower for kw in GRAPH_KEYWORDS)


def _detect_graph_type(message: str) -> str:
    """Détecte le type de graphique adapté selon le message."""
    lower = message.lower()
    if any(kw in lower for kw in PIE_KEYWORDS):
        return 'pie'
    if any(kw in lower for kw in LINE_KEYWORDS):
        return 'line'
    if any(kw in lower for kw in BAR_KEYWORDS):
        return 'bar'
    return 'bar'  # Défaut


def _is_greeting(message: str) -> bool:
    cleaned = message.strip().lower()
    return (
        len(cleaned) < 25
        and any(cleaned.startswith(g) or cleaned == g for g in GREETINGS)
    )


# ══════════════════════════════════════════════════════════════════
#  RBAC — Vérification côté Python (avant l'IA)
# ══════════════════════════════════════════════════════════════════

# Mots-clés sensibles pour le staff médical
def _detect_sensitive_question(user_msg: str, user_role: str):
    """
    Déclenche une alerte admin quand N'IMPORTE QUEL utilisateur
    pose une question sur un module auquel il n'a PAS accès.
    """
    try:
        from flask import session as flask_session
        user_id   = flask_session.get('user_id')
        user_name = flask_session.get('username', user_role)
        if user_id:
            user_db   = DataBaseImacab.get_user_by_id(user_id)
            real_role = user_db.get('role', user_role).lower() if user_db else user_role.lower()
        else:
            real_role = user_role.lower()
    except Exception:
        real_role = user_role.lower()
        user_id   = None
        user_name = user_role

    if real_role == 'admin':
        return  # admin a tous les droits

    msg_lower    = user_msg.lower()
    role_perms   = _get_permissions_from_db(real_role)
    blocked = []

    for module, keywords in MODULE_KEYWORDS.items():
        if role_perms:
            perm       = role_perms.get(module, '✗')
            has_access = perm in ('✓', 'R/W')
        else:
            allowed    = ROLE_ALLOWED_TABLES.get(real_role, [])
            static_map = {
                'PROD.':  'production'    in allowed,
                'MAINT.': 'maintenance'   in allowed,
                'VENTES': 'ventes'        in allowed,
                'MED.':   'suivi_medical' in allowed,
                'CABLES': 'cables'        in allowed,
            }
            has_access = static_map.get(module, False)

        if not has_access and any(kw in msg_lower for kw in keywords):
            blocked.append(module)

    if blocked:
        try:
            alert_id = DataBaseImacab.save_sensitive_alert(
                user_id=user_id,
                user_name=user_name,
                user_role=real_role,
                question_text=f"[Modules interdits: {', '.join(blocked)}] {user_msg}"
            )
            logger.warning(f"⚠️ ALERTE — {user_name} ({real_role}) → {blocked} : {user_msg[:80]}")
            return alert_id
        except Exception as e:
            logger.error(f"Erreur save_sensitive_alert: {e}")
    return None


# Correspondance modules dashboard -> mots-cles SQL
MODULE_KEYWORDS = {
    'PROD.':  ['production', 'vitesse', 'tension', 'cable', 'fabrication', 'ligne'],
    'MAINT.': ['maintenance', 'panne', 'reparation', 'machine', 'entretien', 'incident', 'incidents', 'accident', 'accidents', 'bris', 'defaillance', 'revision', 'vidange', 'diagnostic', 'intervention'],
    'VENTES': ['vente', 'ventes', 'chiffre', 'client', 'montant', 'revenu', 'vendu', 'combien', 'ca '],
    'MED.':   [
        'medical', 'medicaux', 'médical', 'médicaux',
        'infirmerie', 'suivi_medical', 'suivi medical',
        'consultation', 'consulte', 'consulté', 'consulter',
        'visite', 'visité', 'passer chez', 'passé chez',
        'blessure', 'blesse', 'blessé', 'accident de travail',
        'sante', 'santé', 'hospitalise', 'hospitalisé',
        'docteur', 'dr ', 'dr.', 'medecin', 'médecin', 'infirmier',
        'alaoui', 'dr.alaoui', 'dr alaoui',
        'bennis', 'dr.bennis', 'dr bennis',
        'berrad', 'dr.berrad', 'dr berrad',
        'traitement', 'prescription', 'medicament', 'médicament',
        'aptitude', 'inapte', 'apte',
    ],
}


def _normalize_module_key(key: str) -> str:
    """
    Normalise une clé de module en supprimant les accents et en la mettant en majuscules.
    """
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', key.upper())
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def _get_permissions_from_db(user_role: str) -> dict:
    """Charge les permissions depuis PostgreSQL, avec normalisation des clés de modules."""
    try:
        pmap = DataBaseImacab.get_permissions_map()
        raw_perms = pmap.get(user_role.lower(), {})
        return {_normalize_module_key(k): v for k, v in raw_perms.items()}
    except Exception as e:
        logger.warning(f"Impossible de charger les permissions: {e}")
        return {}


def _check_rbac(user_msg: str, user_role: str):
    """
    Verifie les droits AVANT d appeler l IA.
    Lit les permissions depuis PostgreSQL — clés normalisées (pas d accents).
    """
    role_lower = user_role.lower()

    if role_lower == 'admin':
        return None

    msg_lower  = user_msg.lower()
    role_perms = _get_permissions_from_db(role_lower)

    if not role_perms:
        # Fallback règles statiques
        allowed = ROLE_ALLOWED_TABLES.get(role_lower, [])
        if '*' in allowed:
            return None
        static_map = {
            'PROD.':  'production' in allowed,
            'MAINT.': 'maintenance' in allowed,
            'VENTES': 'ventes' in allowed,
            'MED.':   'suivi_medical' in allowed,
            'CABLES': 'cables' in allowed,
        }
        for module, keywords in MODULE_KEYWORDS.items():
            if not static_map.get(module, False) and any(kw in msg_lower for kw in keywords):
                return (
                    f"🔒 Accès refusé : votre rôle **{user_role.upper()}** "
                    f"ne permet pas d'accéder aux données '{module}'."
                )
        return None

    # Permissions depuis la BD (clés normalisées)
    for module, keywords in MODULE_KEYWORDS.items():
        perm       = role_perms.get(module, '✗')
        has_access = perm in ('✓', 'R/W')
        if not has_access and any(kw in msg_lower for kw in keywords):
            return (
                f"🔒 Accès refusé : votre rôle **{user_role.upper()}** "
                f"ne permet pas d'accéder aux données '{module}'."
            )
    return None


def notify_permission_change(role: str, module: str, permission: str):
    """Appelee depuis app.py quand l admin change une permission."""
    logger.info(f"Permission mise a jour: {role}/{module} = {permission}")


# ══════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════════

def _get_aliases_text() -> str:
    aliases_json = DataBaseImacab.get_bot_metadata("dictionnaire_metier")
    if not aliases_json:
        return ""
    try:
        aliases = json.loads(aliases_json)
        if aliases:
            return (
                "DICTIONNAIRE MÉTIER (ALIASES) :\n"
                + "\n".join(f"- '{k}' correspond à la colonne/table '{v}'"
                            for k, v in aliases.items())
                + "\n\n"
            )
    except Exception:
        pass
    return ""


def _extract_json(content: str):
    """Extrait le JSON propre même si entouré de balises Markdown."""
    cleaned = re.sub(r'```(?:json)?\s*', '', content).replace('```', '').strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
        if 'sql' in parsed or 'erreur' in parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def _sanitize_sql(sql: str) -> str:
    """Corrige les erreurs courantes de l'IA (syntaxe MySQL au lieu de PostgreSQL)."""
    # Remplace YEAR(col) par EXTRACT(YEAR FROM col)
    sql = re.sub(r'YEAR\(([^)]+)\)', r'EXTRACT(YEAR FROM \1)', sql, flags=re.IGNORECASE)
    # Remplace MONTH(col) par EXTRACT(MONTH FROM col)
    sql = re.sub(r'MONTH\(([^)]+)\)', r'EXTRACT(MONTH FROM \1)', sql, flags=re.IGNORECASE)

    # ✅ CORRECTIONS suivi_medical — remplace toute référence à employe_id ou user_id
    #    par matricule (vrai nom de colonne dans le fichier Excel importé)
    sql = re.sub(r'suivi_medical\.employe_id', 'suivi_medical.matricule', sql, flags=re.IGNORECASE)
    sql = re.sub(r'suivi_medical\.user_id',    'suivi_medical.matricule', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bsm\.employe_id\b',        'sm.matricule',            sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bsm\.user_id\b',           'sm.matricule',            sql, flags=re.IGNORECASE)

    # ✅ Corrige aussi le nom de colonne medecin → medecin_traitant si l'IA utilise le mauvais nom
    sql = re.sub(r'\bsm\.medecin\b',           'sm.medecin_traitant',     sql, flags=re.IGNORECASE)
    sql = re.sub(r'suivi_medical\.medecin\b',  'suivi_medical.medecin_traitant', sql, flags=re.IGNORECASE)

    # ✅ Supprime les jointures inutiles avec users (les noms sont déjà dans nom_employe)
    sql = re.sub(
        r'JOIN\s+public\."users"\s+\w+\s+ON\s+\w+\.id\s*=\s*\w+\.matricule',
        '',
        sql,
        flags=re.IGNORECASE
    )

    return sql


def _generate_story(user_msg: str, rows: list, user_role: str = 'operateur') -> str:
    """
    Data Storytelling — appelle Ollama une 2e fois avec les données brutes
    pour produire un mini-rapport analytique en langage naturel.
    """
    if not rows or len(rows) < 2:
        return ''
    sample = rows[:30]
    rows_text = '\n'.join(str(r) for r in sample)
    prompt = f"""Tu es un analyste de données industrielles pour l'usine IMACAB.
L'utilisateur a demandé : « {user_msg} »

Voici les données extraites :
{rows_text}

Écris un résumé analytique en 2-3 phrases MAXIMUM en français.
- Identifie la tendance principale (hausse, baisse, stable).
- Mentionne la valeur la plus haute ou la plus basse si pertinent.
- Sois précis et factuel. Pas d'introduction. Pas de "voici les données".
- Commence directement : "La production a atteint..." ou "Les ventes montrent..."
Réponse :"""
    try:
        _t0 = time.time()
        resp = ollama.chat(
            model='mistral:7b-instruct-q4_K_M',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.3, 'num_predict': 150, 'num_ctx': 2048},
            keep_alive='30m'  # ✅ garde le modèle chargé en VRAM 30 min au lieu de 5 par défaut
        )
        logger.info(f"⏱️ [Ollama] génération story: {time.time() - _t0:.1f}s")
        story = resp['message']['content'].strip()
        story = re.sub(r'^(Réponse|Résumé)\s*:\s*', '', story, flags=re.IGNORECASE).strip()
        return story
    except Exception as e:
        logger.warning(f"⚠️ _generate_story failed: {e}")
        return ''


def _execute_and_format(sql: str, question: str, user_role: str = 'operateur') -> dict:
    """
    Exécute le SQL généré par l'IA, formate la réponse en texte lisible,
    et génère un résumé analytique (data storytelling) via Ollama.
    """
    sql = _sanitize_sql(sql)
    results = DataBaseImacab.executer_requete_ia(sql)

    if isinstance(results, dict) and ('error' in results or 'erreur' in results):
        err = results.get('error', results.get('erreur', 'Erreur inconnue'))
        logger.error(f"❌ Erreur SQL: {err}")
        return {
            'type': 'text',
            'text': f"⚠️ Erreur lors de l'exécution : {err}",
            'story': ''
        }

    if not results:
        return {'type': 'text', 'text': "Aucun résultat trouvé pour cette requête.", 'story': ''}

    lines = []
    for row in results:
        parts = []
        for k, v in row.items():
            if v is not None:
                val_str = str(v)
                if hasattr(v, 'strftime'):
                    val_str = v.strftime('%d/%m/%Y %H:%M') if hasattr(v, 'hour') else v.strftime('%d/%m/%Y')
                parts.append(f"{k.replace('_', ' ').capitalize()} : {val_str}")
        lines.append(f"• {' | '.join(parts)}")

    header = f"**{len(results)} résultat(s) :**\n"
    text   = header + "\n".join(lines)

    story = _generate_story(question, results, user_role)

    return {'type': 'text', 'text': text, 'story': story}


# ══════════════════════════════════════════════════════════════════
#  PROMPTS
# ══════════════════════════════════════════════════════════════════

def _build_sql_prompt(user_msg: str, schema: str, user_role: str) -> str:
    role_lower = user_role.lower()
    allowed_tables = ROLE_ALLOWED_TABLES.get(role_lower, [])
    if '*' in allowed_tables:
        excel_tables = etl_pipeline._load_excel_cache().keys()
        table_list = ', '.join(excel_tables) or 'production, maintenance, ventes'
    else:
        table_map = {
            'production':    'production',
            'maintenance':   'maintenaince',
            'ventes':        'ventes',
            'suivi_medical': 'suivi_medical',
            'users':         'users',
            'cables':        'cables',
        }
        table_list = ', '.join(table_map.get(t, t) for t in allowed_tables if t in table_map)
    return f"""Tu es un générateur SQL expert pour PostgreSQL.
Base de données de l'usine IMACAB.

SCHÉMA COMPLET AVEC DONNÉES RÉELLES :
{schema}

RÔLE UTILISATEUR : {user_role.upper()}
DROITS : {ROLE_ACCESS.get(user_role.lower(), ROLE_ACCESS['operateur'])}

QUESTION : {user_msg}

MISSION : Génère la requête SQL SELECT qui répond à cette question.

RÈGLES ABSOLUES :
1. Réponds UNIQUEMENT avec la requête SQL brute. Rien d'autre.
2. Pas de texte avant, pas de commentaires, pas de backticks.
3. Utilise EXACTEMENT les noms de tables et colonnes du schéma ci-dessus.
4. Toujours préfixer avec public."nom_table"
5. Si la question ne nécessite pas de SQL → réponds : NOQUERY
6. Génère UNE SEULE requête terminée par un point-virgule `;`
7. INTERDIT d'écrire des explications ou du texte additionnel.
8. ATTENTION AUX DATES : Si on te demande "cette semaine" ou "récent", cherche la MAX(date) dans la table plutôt que CURRENT_DATE, car les données peuvent être anciennes.
9. NOMS DE TABLES RÉELS (utilise UNIQUEMENT ces noms) :
   - ventes (PAS ventes_usine)
   - production (PAS production_cables)
   - maintenaince (PAS maintenance_machines — note: maintenaince avec 'i')
   - suivi_medical, cables, users
10. SYNTAXE POSTGRESQL : Pour extraire l'année ou le mois, utilise EXTRACT(YEAR FROM date_col) ou EXTRACT(MONTH FROM date_col). INTERDIT d'utiliser YEAR() ou MONTH().

11. TABLE suivi_medical — RÈGLES CRITIQUES :
    ⚠️ Cette table contient DÉJÀ les noms des employés. PAS BESOIN de jointure avec users.
    - Colonnes disponibles (utilise EXACTEMENT ces noms) :
        date_visite, nom_employe, matricule, type_visite,
        medecin_traitant, resultat, commentaire
    - Pour chercher un médecin → WHERE sm.medecin_traitant ILIKE '%Bennis%'
    - Pour "noms des employés" → SELECT sm.nom_employe, sm.date_visite, sm.medecin_traitant
    - Pour "qui a passé chez..." → SELECT sm.nom_employe, sm.date_visite, sm.type_visite
      FROM public."suivi_medical" sm WHERE sm.medecin_traitant ILIKE '%nom_medecin%'
    - Pour "combien d'employés..." → SELECT COUNT(*) FROM public."suivi_medical" sm
    - NE JAMAIS utiliser employe_id, user_id, medecin — ces colonnes N'EXISTENT PAS.
    - NE JAMAIS faire JOIN avec users pour suivi_medical.
    - Toujours ORDER BY sm.date_visite DESC LIMIT 100

12. FORMAT GÉNÉRAL DES QUESTIONS MÉDICALES :
    - "donne moi les noms..." → SELECT sm.nom_employe
    - "qui a passé..." → SELECT sm.nom_employe, sm.date_visite, sm.medecin_traitant
    - "combien d'employés..." → SELECT COUNT(*)
    - "les visites de..." → WHERE sm.medecin_traitant ILIKE '%nom%'

Tables disponibles : {table_list}"""


def _build_graph_prompt(user_msg: str, schema: str, user_role: str, graph_hint: str) -> str:
    role_info = ROLE_ACCESS.get(user_role.lower(), ROLE_ACCESS['operateur'])
    droits = role_info.get('description', user_role.upper())
    aliases_text = _get_aliases_text()

    prompt = DataBaseImacab.get_bot_metadata('system_prompt_graphique')

    if not prompt:
        prompt = f"""Tu es l'assistant expert de l'usine IMACAB (fabrication de câbles).

RÔLE DE L'UTILISATEUR : {{role}}
DROITS D'ACCÈS : {{droits}}

════════════════════════════════════════════════════════
STRUCTURE RÉELLE DE LA BASE AVEC TOUTES LES DONNÉES :
════════════════════════════════════════════════════════
{{schema}}
════════════════════════════════════════════════════════

MISSION : Générer un JSON de graphique avec une requête SQL correcte.
TYPE DE GRAPHIQUE OBLIGATOIRE : {graph_hint}
⚠️ IMPORTANT : Le champ "graph_type" dans ta réponse JSON DOIT être exactement "{graph_hint}".

RÈGLES ABSOLUES :
1. Réponds UNIQUEMENT avec un objet JSON valide. Zéro texte avant ou après.
2. Pas de balises Markdown. JSON brut directement.
3. La requête SQL doit utiliser les VRAIS noms de tables et colonnes du schéma.
4. Toujours préfixer : FROM public."nom_table"
5. Si accès refusé → {{"erreur": "Accès refusé : [raison]"}}
6. Pour les VENTES, privilégie TOUJOURS "bar" pour les comparaisons par semaine ou mois.
7. Pour grouper par date : utilise date_trunc('week', date_col) ou date_trunc('month', date_col).
8. NOMS DE TABLES RÉELS :
   - ventes (PAS ventes_usine, PAS sales)
   - production (PAS production_cables, PAS prod)
   - maintenaince (PAS maintenance, PAS maintenance_machines)
   - suivi_medical, cables, users
9. SYNTAXE POSTGRESQL : TOUJOURS EXTRACT(YEAR FROM date_col). JAMAIS YEAR() ni MONTH().
10. TABLE suivi_medical — RÈGLES CRITIQUES :
    ⚠️ Cette table contient DÉJÀ les noms des employés. PAS BESOIN de jointure.
    - Colonnes : date_visite, nom_employe, matricule, type_visite, medecin_traitant, resultat, commentaire
    - NE JAMAIS utiliser employe_id, user_id, medecin (colonnes inexistantes).
    - NE JAMAIS faire JOIN avec users pour suivi_medical.

FORMAT JSON EXACT :
{{
  "sql": "SELECT col1, col2 FROM public.\\"nom_table\\" ORDER BY col1 LIMIT 100",
  "titre": "Titre lisible du graphique",
  "graph_type": "{graph_hint}",
  "x_axis": "nom_colonne_axe_x",
  "y_axis": "nom_colonne_axe_y"
}}"""

    return (
        prompt
        .replace("{role}", user_role.upper())
        .replace("{droits}", droits)
        .replace("{schema}", aliases_text + schema)
    )


# ══════════════════════════════════════════════════════════════════
#  RÉPONSE FALLBACK DEPUIS LE SCHÉMA
# ══════════════════════════════════════════════════════════════════

def _answer_from_schema(user_msg: str, schema: str, user_role: str) -> str:
    """Fallback : l'IA répond directement depuis le schéma sans générer de SQL."""
    role_info = ROLE_ACCESS.get(user_role.lower(), ROLE_ACCESS['operateur'])
    droits = role_info.get('description', user_role.upper())
    aliases_text = _get_aliases_text()

    system = f"""Tu es l'assistant expert de l'usine IMACAB.
RÔLE : {user_role.upper()}
DROITS : {droits}

{aliases_text}DONNÉES RÉELLES (SEULE SOURCE AUTORISÉE) :
{schema}

RÈGLE N°1 : Utilise UNIQUEMENT les noms, valeurs et données qui apparaissent dans le bloc ci-dessus.
JAMAIS d'invention. JAMAIS de nom qui n'est pas dans le schéma.

RÈGLE N°2 : Réponse en texte simple, concis, sans JSON ni Markdown.
RÈGLE N°3 TABLE suivi_medical :
  - Colonnes disponibles : date_visite, nom_employe, matricule, type_visite, medecin_traitant, resultat, commentaire
  - NE JAMAIS utiliser employe_id, user_id, medecin (colonnes inexistantes).
  - PAS de jointure avec users nécessaire."""

    try:
        resp = ollama.chat(
            model='mistral:7b-instruct-q4_K_M',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user',   'content': user_msg}
            ],
            options={'temperature': 0.0, 'num_ctx': 4096, 'num_predict': 500}
        )
        return resp['message']['content'].strip()
    except Exception as e:
        return f"Erreur : {str(e)}"


# ══════════════════════════════════════════════════════════════════
#  RBAC HELPERS (compatibilité)
# ══════════════════════════════════════════════════════════════════

def check_access(user_role, table_name):
    if user_role not in ROLE_ALLOWED_TABLES:
        return False
    allowed = ROLE_ALLOWED_TABLES[user_role]
    if '*' in allowed:
        return True
    return table_name in allowed


def extract_table_from_sql(sql_query):
    try:
        sql_upper = sql_query.upper()
        if 'FROM' in sql_upper:
            parts = sql_upper.split('FROM')
            if len(parts) > 1:
                table_part = parts[1].strip().split()[0]
                return table_part.strip(';').strip('"').lower()
        return 'unknown'
    except Exception:
        return 'unknown'


def get_role_info(user_role):
    return ROLE_ACCESS.get(user_role)


# ══════════════════════════════════════════════════════════════════
#  HANDLER INSPECTION DB
# ══════════════════════════════════════════════════════════════════

def _handle_inspect(action: str, extras: dict, user_role: str) -> dict:
    """
    Exécute l'action d'inspection demandée et retourne un dict standardisé.
    """
    allowed = ('admin', 'directeur', 'responsable')
    if user_role.lower() not in allowed:
        return {
            "type": "text",
            "text": (
                f"🔒 L'inspection de la base de données est réservée aux rôles "
                f"admin, directeur et responsable. "
                f"Votre rôle actuel ({user_role.upper()}) ne permet pas cette opération."
            )
        }

    logger.info(f"🔍 Inspection DB: {action} | extras={extras} | rôle={user_role}")

    try:
        if action == "analyze_tables":
            data = db_inspector.analyze_tables(include_internal=(user_role == 'admin'))

        elif action == "get_relations":
            table_a = extras.get("table_a")
            table_b = extras.get("table_b")
            if table_a and table_b:
                data = db_inspector.get_relation_between(table_a, table_b)
            else:
                data = db_inspector.get_relations(include_internal=(user_role == 'admin'))

        elif action == "detect_nulls":
            data = db_inspector.detect_nulls(include_internal=(user_role == 'admin'))

        elif action == "detect_duplicates":
            data = db_inspector.detect_duplicates(include_internal=(user_role == 'admin'))

        else:
            return {"type": "text", "text": "Action d'inspection inconnue."}

        if "error" in data:
            return {"type": "text", "text": f"❌ Erreur lors de l'inspection : {data['error']}"}

        return {"type": "inspect", "action": action, "data": data}

    except Exception as e:
        logger.error(f"❌ _handle_inspect {action}: {e}")
        return {"type": "text", "text": f"❌ Erreur lors de l'inspection : {str(e)}"}


# ══════════════════════════════════════════════════════════════════
#  FONCTION PRINCIPALE
# ══════════════════════════════════════════════════════════════════

def generer_sql(user_msg: str, original_msg: str = None, user_role: str = 'operateur'):
    """
    Traite le message utilisateur et retourne :
    - str  → réponse texte à afficher directement (cas par défaut)
    - dict → {"sql":..., "titre":..., "graph_type":...} UNIQUEMENT si l'utilisateur
             demande explicitement un graphique
    """

    # ── 0. Commandes d'inspection DB — intercept avant tout ───────
    inspect_action, inspect_extras = db_inspector.detect_inspect_intent(user_msg)
    if inspect_action:
        return _handle_inspect(inspect_action, inspect_extras, user_role)

    # ── 1. Salutations courtes — réponse immédiate sans Ollama ─────
    if _is_greeting(user_msg):
        return "Bonjour ! Comment puis-je vous assister avec les données de l'usine ?"

    # ── 2. Vérification RBAC côté Python (avant l'IA) ─────────────
    clean_msg = original_msg if original_msg else user_msg
    rbac_error = _check_rbac(clean_msg, user_role)
    if rbac_error:
        return rbac_error

    # ── 3. Schéma filtré (depuis le cache, tables pertinentes seulement)
    schema = _get_relevant_schema(user_msg)

    # ── 4. Détection du mode : graphique OU texte ──────────────────
    wants_graph = _wants_graph(user_msg)
    logger.info(f"💬 Mode: {'GRAPHIQUE' if wants_graph else 'TEXTE'} | Rôle: {user_role}")

    # ════════════════════════════════════════════════════════════════
    #  MODE TEXTE (défaut — question normale sans mot graphique)
    # ════════════════════════════════════════════════════════════════
    if not wants_graph:
        sql_prompt = _build_sql_prompt(user_msg, schema, user_role)

        try:
            _t_sql = time.time()
            resp_sql = ollama.chat(
                model='mistral:7b-instruct-q4_K_M',
                messages=[
                    {
                        'role': 'system',
                        'content': "Tu es un générateur SQL PostgreSQL. Tu réponds UNIQUEMENT avec du SQL brut ou le mot NOQUERY."
                    },
                    {'role': 'user', 'content': sql_prompt}
                ],
                options={
                    'temperature': 0.0,
                    'num_predict': 250,
                    'num_ctx': 4096,
                },
                keep_alive='30m'  # ✅ garde le modèle chargé en VRAM 30 min au lieu de 5 par défaut
            )
            logger.info(f"⏱️ [Ollama] génération SQL: {time.time() - _t_sql:.1f}s")
            sql_raw = resp_sql['message']['content'].strip()

            # Extraction robuste du SQL
            match_code = re.search(r'```(?:sql)?\s*(.*?)\s*```', sql_raw, re.DOTALL | re.IGNORECASE)
            if match_code:
                sql_clean = match_code.group(1).strip()
            else:
                match_select = re.search(r'(SELECT.*?;)', sql_raw, re.DOTALL | re.IGNORECASE)
                if match_select:
                    sql_clean = match_select.group(1).strip()
                else:
                    sql_clean = re.sub(r'```(?:sql)?\s*', '', sql_raw).replace('```', '').strip()

            # Si pas de SQL valide → fallback schéma
            if 'NOQUERY' in sql_clean.upper() or not sql_clean.upper().strip().startswith('SELECT'):
                return _answer_from_schema(user_msg, schema, user_role)

            # Exécuter le SQL et formater en texte
            logger.info(f"🔍 SQL généré : {sql_clean[:150]}...")
            formatted = _execute_and_format(sql_clean, user_msg, user_role)
            DataBaseImacab.log_chat(user_msg, sql_clean, True)
            return formatted

        except Exception as e:
            logger.error(f"❌ Erreur mode texte : {e}")
            return f"Erreur de communication avec l'IA : {str(e)}"

    # ════════════════════════════════════════════════════════════════
    #  MODE GRAPHIQUE (uniquement si demandé explicitement)
    # ════════════════════════════════════════════════════════════════
    graph_type_hint = _detect_graph_type(user_msg)
    graph_prompt = _build_graph_prompt(user_msg, schema, user_role, graph_type_hint)

    try:
        _t_graph = time.time()
        response = ollama.chat(
            model='mistral:7b-instruct-q4_K_M',
            messages=[
                {'role': 'system', 'content': graph_prompt},
                {'role': 'user',   'content': user_msg}
            ],
            options={
                'temperature': 0.1,
                'num_predict': 350,
                'num_ctx': 4096,
            },
            keep_alive='30m'  # ✅ garde le modèle chargé en VRAM 30 min au lieu de 5 par défaut
        )
        logger.info(f"⏱️ [Ollama] génération graphique: {time.time() - _t_graph:.1f}s")
        content = response['message']['content'].strip()
        logger.info(f"🤖 Réponse IA graphique brute : {content[:200]}...")

        parsed = _extract_json(content)
        if parsed and 'sql' in parsed:
            parsed['sql'] = _sanitize_sql(parsed['sql'])
            parsed['graph_type'] = graph_type_hint
            logger.info(f"✅ JSON graphique extrait : {parsed.get('graph_type')} | {parsed.get('titre', '')}")
            return parsed

        logger.warning("⚠️  L'IA n'a pas produit de JSON valide pour le graphique")
        return content

    except Exception as e:
        logger.error(f"❌ Erreur mode graphique : {e}")
        return f"Erreur de communication avec l'IA : {str(e)}"


# ══════════════════════════════════════════════════════════════════
#  TEST STANDALONE
# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("📊 MATRICE RBAC IMACAB")
    print("=" * 80)
    for role, info in ROLE_ACCESS.items():
        print(f"\n👤 {role.upper()}")
        print(f"   {info['description']}")
        print(f"   Tables : {', '.join(ROLE_ALLOWED_TABLES[role])}")

    print("\n" + "=" * 80)
    print("🧪 Test détection mode graphique")
    print("=" * 80)
    tests = [
        ("Quelle est la tension aujourd'hui ?",          False),
        ("Montre la tension en graphique",               True),
        ("Donne-moi la production du jour",             False),
        ("Affiche l'évolution de la vitesse en courbe", True),
        ("Compare machine A et B en graphe",            True),
        ("Répartition des pannes en camembert",         True),
        ("Combien de câbles produits ?",                False),
    ]
    for msg, expected in tests:
        result = _wants_graph(msg)
        status = "✅" if result == expected else "❌"
        print(f"  {status} [{('GRAPH' if result else 'TEXTE'):5}] {msg}")