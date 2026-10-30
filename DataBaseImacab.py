def create_permissions_table():
    """Crée la table permissions si elle n'existe pas"""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS permissions (
                id SERIAL PRIMARY KEY,
                role VARCHAR(50) NOT NULL,
                module VARCHAR(50) NOT NULL,
                permission VARCHAR(10) NOT NULL,
                UNIQUE(role, module)
            );
            -- Insérer les permissions par défaut si la table est vide
            INSERT INTO permissions (role, module, permission) VALUES
                ('admin',       'PROD.',   '✓'),
                ('admin',       'MAINT.',  '✓'),
                ('admin',       'VENTES',  '✓'),
                ('admin',       'MÉD.',    '✓'),
                ('directeur',   'PROD.',   '✓'),
                ('directeur',   'MAINT.',  'R/W'),
                ('directeur',   'VENTES',  '✓'),
                ('directeur',   'MÉD.',    '✗'),
                ('responsable', 'PROD.',   '✓'),
                ('responsable', 'MAINT.',  'R/W'),
                ('responsable', 'VENTES',  '✓'),
                ('responsable', 'MÉD.',    '✗'),
                ('medical',     'PROD.',   '✗'),
                ('medical',     'MAINT.',  'R/W'),
                ('medical',     'VENTES',  '✗'),
                ('medical',     'MÉD.',    '✓'),
                ('operateur',   'PROD.',   '✓'),
                ('operateur',   'MAINT.',  '✗'),
                ('operateur',   'VENTES',  '✗'),
                ('operateur',   'MÉD.',    '✗')
            ON CONFLICT (role, module) DO NOTHING;
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Table permissions créée ou déjà existante")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur création table permissions: {e}")
        return False

def get_permissions():
    """Récupère toutes les permissions sous forme de liste de dicts"""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT role, module, permission FROM permissions")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"❌ Erreur récupération permissions: {e}")
        return []

def get_permissions_map():
    """Retourne les permissions sous forme de dict {role: {module: permission}} pour l IA."""
    conn = get_connection()
    if not conn:
        return {}
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT role, module, permission FROM permissions")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        pmap = {}
        for r in rows:
            role = r['role'].lower()
            module = r['module'].upper()
            if role not in pmap:
                pmap[role] = {}
            pmap[role][module] = r['permission']
        return pmap
    except Exception as e:
        logger.error(f"❌ Erreur get_permissions_map: {e}")
        return {}


def set_permission(role, module, permission):
    """Ajoute ou met à jour une permission pour un rôle et un module"""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO permissions (role, module, permission)
            VALUES (%s, %s, %s)
            ON CONFLICT (role, module)
            DO UPDATE SET permission = EXCLUDED.permission;
        ''', (role, module, permission))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Permission {role}/{module} = {permission} enregistrée")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur set_permission: {e}")
        return False

def get_distinct_modules():
    """Retourne la liste ordonnée des modules distincts depuis la table permissions.
    Utilisé par le frontend pour construire dynamiquement les colonnes de la matrice RBAC.
    Quand une nouvelle table est ajoutée via add_module_to_permissions(),
    elle apparaît automatiquement dans le dashboard sans toucher au code.
    """
    conn = get_connection()
    if not conn:
        return ['PROD.', 'MAINT.', 'VENTES', 'MÉD.']
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT module FROM permissions ORDER BY module")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"❌ Erreur get_distinct_modules: {e}")
        return ['PROD.', 'MAINT.', 'VENTES', 'MÉD.']

def add_module_to_permissions(module: str):
    """Ajoute un nouveau module dans la matrice RBAC pour TOUS les rôles.
    Permission par défaut = '✗' — l'admin choisit ensuite case par case.
    Exemple : add_module_to_permissions('QUALITE')
    """
    ALL_ROLES = ['admin', 'directeur', 'responsable', 'medical', 'operateur']
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        for role in ALL_ROLES:
            cursor.execute('''
                INSERT INTO permissions (role, module, permission)
                VALUES (%s, %s, '✗')
                ON CONFLICT (role, module) DO NOTHING;
            ''', (role, module.upper()))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Module '{module}' ajouté dans la matrice RBAC pour tous les rôles")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur add_module_to_permissions: {e}")
        return False


def delete_module_from_permissions(module: str):
    """Supprime un module de la matrice RBAC — supprime TOUTES les lignes
    de la table permissions dont le module correspond (insensible à la casse).
    Exemple : delete_module_from_permissions('QUALITE')
    """
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM permissions WHERE UPPER(module) = UPPER(%s)",
            (module.strip(),)
        )
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Module '{module}' supprimé ({deleted} règle(s) effacée(s))")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur delete_module_from_permissions: {e}")
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return False

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash
import logging
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Configuration PostgreSQL UNIFIÉE - SANS LE "S"
DB_CONFIG = {
    'host': 'localhost',
    'database': 'usine_cables',  # ✅ UNIFIÉ (sans s)
    'user': 'postgres',
    'password': '0123',
    'port': 5432
}

SQLALCHEMY_URI = 'postgresql://postgres:0123@localhost:5432/usine_cables'

# ══════════════════════════════════════════════════════════════════
#  CONNEXION
# ══════════════════════════════════════════════════════════════════

def get_connection():
    """Crée une connexion à PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        logger.info("✅ Connexion PostgreSQL établie")
        return conn
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur de connexion PostgreSQL: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  AUTH & UTILISATEURS
# ══════════════════════════════════════════════════════════════════

def check_credentials(email, password):
    """Vérifie les identifiants de l'utilisateur"""
    conn = get_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute(
            "SELECT id, username, email, password_hash, role, is_admin, is_active FROM users WHERE email = %s",
            (email,)
        )
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not user:
            logger.warning(f"❌ Utilisateur {email} non trouvé")
            return None
        
        if not user['is_active']:
            logger.warning(f"❌ Utilisateur {email} désactivé")
            return None
        
        if check_password_hash(user['password_hash'], password):
            logger.info(f"✅ Connexion réussie: {email}")
            return dict(user)
        else:
            logger.warning(f"❌ Mot de passe incorrect pour {email}")
            return None
            
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur requête PostgreSQL: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return None

def get_user_by_email(email):
    """Récupère un utilisateur par email"""
    conn = get_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return dict(user) if user else None
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return None

def get_user_by_id(user_id):
    """Récupère un utilisateur par ID"""
    conn = get_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return dict(user) if user else None
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return None

def get_all_users():
    """Récupère tous les utilisateurs"""
    conn = get_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, username, email, role, is_active, is_online, last_login FROM users ORDER BY id")
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        logger.info(f"✅ {len(users)} utilisateurs récupérés")
        return [dict(u) for u in users]
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return []

# ──────────────────────────────────────────────────────
#  SENSITIVE ALERTS (DASHBOARD)
#  ⚠️  Toutes les fonctions utilisent la table v2 :
#       colonnes : id, user_id, user_name, user_role, question_text, seen, created_at
# ──────────────────────────────────────────────────────

# --- STUB pour compatibilité ancienne signature (ollamaAi v1) ---
# La vraie implémentation est plus bas (save_sensitive_alert v2, ligne ~755)
# Cette fonction est intentionnellement vide — ne pas utiliser.

def get_unseen_alerts():
    """
    Alias vers get_unseen_sensitive_alerts() — utilisé par app.py /api/admin/alerts/sensitive.
    Retourne les alertes non vues depuis la table v2.
    """
    return get_unseen_sensitive_alerts()

def mark_alert_seen(alert_id):
    """Alias vers mark_alert_as_seen() — utilisé par app.py."""
    conn = get_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        # Compatibilité : essaie les deux noms de colonne
        cursor.execute("UPDATE sensitive_alerts SET seen = TRUE WHERE id = %s", (alert_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Erreur mark_alert_seen: {e}")
        return False

def get_users_by_role():
    """Retourne le nombre d'utilisateurs ACTIFS par rôle"""
    conn = get_connection()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT role, COUNT(*) as count 
            FROM users 
            WHERE is_active = TRUE 
            GROUP BY role 
            ORDER BY role
        """)
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Convertir en dict {role: count}
        role_counts = {}
        for row in results:
            role_counts[row['role']] = row['count']
        
        logger.info(f"✅ Répartition par rôle: {role_counts}")
        return role_counts
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return {}
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return {}

def get_online_users():
    """Récupère les utilisateurs vraiment actifs (last_seen < 5 minutes)"""
    conn = get_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, username, email, role, is_online, last_activity
            FROM users
            WHERE is_online = TRUE AND is_active = TRUE
            AND (
                last_seen > NOW() - INTERVAL '10 minutes'
                OR last_activity > NOW() - INTERVAL '10 minutes'
            )
            ORDER BY last_activity DESC NULLS LAST
        """)
        users = cursor.fetchall()

        # Mettre is_online=FALSE pour ceux qui ne sont plus actifs
        cursor.execute("""
            UPDATE users SET is_online = FALSE
            WHERE is_online = TRUE
            AND (last_seen IS NULL OR last_seen < NOW() - INTERVAL '10 minutes')
            AND (last_activity IS NULL OR last_activity < NOW() - INTERVAL '10 minutes')
        """)
        conn.commit()

        cursor.close()
        conn.close()
        logger.info(f"✅ {len(users)} utilisateurs en ligne")
        return [dict(u) for u in users]
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return []

def get_login_logs():
    """Alias de get_security_logs — appelé par app.py"""
    return get_security_logs()

def get_security_logs():
    """Récupère les logs de sécurité"""
    conn = get_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT l.id, l.user_id, u.username, u.email, l.login_time, l.success, l.reason, l.ip_address
            FROM login_logs l
            LEFT JOIN users u ON l.user_id = u.id
            ORDER BY l.login_time DESC
            LIMIT 50
        """)
        logs = cursor.fetchall()
        cursor.close()
        conn.close()
        logger.info(f"✅ {len(logs)} logs de sécurité récupérés")
        return [dict(l) for l in logs]
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return []

def get_kpi_stats():
    """Retourne les KPI pour le dashboard : total users, online, chats, success rate"""
    conn = get_connection()
    if not conn:
        return {
            "total_users": 0,
            "online_users": 0,
            "total_chats": 0,
            "success_rate": 0
        }
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Total utilisateurs
        cursor.execute("SELECT COUNT(*) as count FROM users")
        total_users = cursor.fetchone()['count']
        
        # Utilisateurs en ligne (last_seen < 5 minutes)
        cursor.execute("""
            SELECT COUNT(*) as count FROM users
            WHERE is_online = TRUE AND is_active = TRUE
            AND last_seen > NOW() - INTERVAL '5 minutes'
        """)
        online_users = cursor.fetchone()['count']
        
        # Total messages chatbot
        cursor.execute("SELECT COUNT(*) as count FROM chat_logs")
        total_chats = cursor.fetchone()['count']
        
        # Taux de succès
        cursor.execute("SELECT COUNT(*) as count FROM chat_logs WHERE success = TRUE")
        successful_chats = cursor.fetchone()['count']
        
        success_rate = int((successful_chats / total_chats * 100)) if total_chats > 0 else 0
        
        cursor.close()
        conn.close()
        
        logger.info(f"✅ KPI Stats - Users: {total_users}, Online: {online_users}, Chats: {total_chats}, Success: {success_rate}%")
        
        return {
            "total_users": total_users,
            "online_users": online_users,
            "total_chats": total_chats,
            "success_rate": success_rate
        }
    except Exception as e:
        logger.error(f"❌ Erreur get_kpi_stats: {e}")
        return {
            "total_users": 0,
            "online_users": 0,
            "total_chats": 0,
            "success_rate": 0
        }

def update_user_role(user_id, new_role):
    """Met à jour le rôle d'un utilisateur"""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET role = %s WHERE id = %s",
            (new_role, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Rôle mis à jour pour l'utilisateur {user_id}: {new_role}")
        return {"success": True, "message": f"Rôle mis à jour: {new_role}"}
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return {"success": False, "error": str(e)}

def update_user_status(user_id, is_active):
    """Active ou désactive un utilisateur"""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_active = %s WHERE id = %s",
            (is_active, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        status = "activé" if is_active else "désactivé"
        logger.info(f"✅ Utilisateur {user_id} {status}")
        return {"success": True, "message": f"Utilisateur {status}"}
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return {"success": False, "error": str(e)}

def set_user_online(user_id, is_online):
    """Met à jour le statut en ligne d'un utilisateur"""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_online = %s, last_activity = NOW(), last_seen = NOW() WHERE id = %s",
            (is_online, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        status = "connecté" if is_online else "déconnecté"
        logger.info(f"✅ Utilisateur {user_id} {status}")
        return {"success": True, "message": f"Utilisateur {status}"}
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return {"success": False, "error": str(e)}

def create_forced_logouts_table():
    """Crée la table forced_logouts si elle n'existe pas."""
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forced_logouts (
                user_id INTEGER PRIMARY KEY,
                forced_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Erreur création forced_logouts: {e}")

def force_logout_user(user_id):
    """Marque un utilisateur pour déconnexion forcée + met is_online=FALSE."""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    try:
        cursor = conn.cursor()
        # Marquer pour déconnexion forcée
        cursor.execute("""
            INSERT INTO forced_logouts (user_id, forced_at)
            VALUES (%s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET forced_at = NOW()
        """, (user_id,))
        # Mettre hors ligne immédiatement
        cursor.execute(
            "UPDATE users SET is_online = FALSE WHERE id = %s",
            (user_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Force-logout enregistré pour user {user_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"❌ Erreur force_logout_user: {e}")
        return {"success": False, "error": str(e)}

def check_forced_logout(user_id):
    """Retourne True si l'utilisateur doit être déconnecté de force."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM forced_logouts WHERE user_id = %s", (user_id,)
        )
        found = cursor.fetchone() is not None
        if found:
            # Supprimer l'entrée — la déconnexion est traitée une seule fois
            cursor.execute(
                "DELETE FROM forced_logouts WHERE user_id = %s", (user_id,)
            )
            conn.commit()
        cursor.close()
        conn.close()
        return found
    except Exception as e:
        logger.error(f"❌ Erreur check_forced_logout: {e}")
        return False

# ══════════════════════════════════════════════════════════════════
#  DASHBOARD (ADMIN ONLY)
# ══════════════════════════════════════════════════════════════════

def get_dashboard_data(user_role=None, is_admin=False):
    """Récupère les données du dashboard (ADMIN ONLY)"""
    # ✅ Vérifier que l'utilisateur est admin
    if not is_admin or user_role != 'admin':
        logger.warning(f"❌ Accès dashboard refusé pour rôle: {user_role}")
        return {
            "error": "Accès admin requis",
            "users": [],
            "online_users": [],
            "security_logs": []
        }
    
    try:
        return {
            "users": get_all_users(),
            "online_users": get_online_users(),
            "security_logs": get_security_logs(),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des données dashboard: {e}")
        return {
            "users": [],
            "online_users": [],
            "security_logs": [],
            "error": str(e)
        }

# ══════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════

def log_login_attempt(user_id, ip_address, success, reason=None):
    """Enregistre une tentative de connexion"""
    conn = get_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO login_logs (user_id, ip_address, success, reason, login_time)
            VALUES (%s, %s, %s, %s, NOW())
        """, (user_id, ip_address, success, reason))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Tentative de connexion enregistrée pour l'utilisateur {user_id}")
        return True
    except psycopg2.Error as e:
        logger.error(f"❌ Erreur PostgreSQL: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return False

def log_chat(question, sql_generated, success):
    """Enregistre un échange chatbot dans chat_logs"""
    conn = get_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_logs (question, sql_generated, success, created_at)
            VALUES (%s, %s, %s, NOW())
        """, (question, sql_generated, success))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Chat log enregistré")
        return True
    except psycopg2.Error as e:
        logger.error(f"❌ log_chat error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return False

# ══════════════════════════════════════════════════════════════════
#  EXECUTION & METADATA
# ══════════════════════════════════════════════════════════════════

def executer_requete_ia(sql_query):
    """Exécute une requête SQL générée par l'IA et retourne les résultats"""
    conn = get_connection()
    if not conn:
        return {"error": "Impossible de se connecter à la base de données"}
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql_query)
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        logger.info(f"✅ Requête IA exécutée: {len(results)} résultats")
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"❌ executer_requete_ia error: {e}")
        return {"error": str(e)}

def get_bot_metadata(key):
    """Récupère une valeur de bot_metadata par clé"""
    conn = get_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT value FROM bot_metadata WHERE key = %s", (key,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row['value'] if row else None
    except Exception as e:
        logger.error(f"❌ get_bot_metadata error: {e}")
        return None

def update_last_seen(user_id):
    """Met à jour le timestamp last_seen de l'utilisateur connecté
    et enregistre la présence dans daily_activity (une ligne par user par jour)."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_seen = NOW() WHERE id = %s", (user_id,))
        # Enregistre la présence du jour — INSERT IF NOT EXISTS pour ne pas dupliquer
        cursor.execute("""
            INSERT INTO daily_activity (user_id, activity_date)
            VALUES (%s, CURRENT_DATE)
            ON CONFLICT (user_id, activity_date) DO NOTHING
        """, (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception:
        return False

def delete_user(user_id):
    """Supprime définitivement un utilisateur."""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Utilisateur {user_id} supprimé")
        return {"success": True}
    except Exception as e:
        logger.error(f"❌ Erreur delete_user: {e}")
        return {"success": False, "error": str(e)}

def disable_and_disconnect_user(user_id):
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_active = FALSE, is_online = FALSE WHERE id = %s",
            (user_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Utilisateur {user_id} désactivé et déconnecté")
        return {"success": True, "message": "Utilisateur désactivé et déconnecté"}
    except Exception as e:
        logger.error(f"❌ Erreur disable_and_disconnect_user: {e}")
        return {"success": False, "error": str(e)}

def enable_user(user_id):
    """Réactive un utilisateur désactivé."""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_active = TRUE WHERE id = %s",
            (user_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Utilisateur {user_id} réactivé")
        return {"success": True, "message": "Utilisateur réactivé"}
    except Exception as e:
        logger.error(f"❌ Erreur enable_user: {e}")
        return {"success": False, "error": str(e)}

def create_user(username, email, password, role):
    """Crée un nouvel utilisateur. Appelé par la route /api/admin/users/create."""
    from werkzeug.security import generate_password_hash
    conn = get_connection()
    if not conn:
        return {'success': False, 'error': 'Erreur de connexion'}
    try:
        cursor = conn.cursor()
        # Vérifier doublon username
        cursor.execute('SELECT id FROM users WHERE username = %s OR email = %s', (username, email))
        if cursor.fetchone():
            return {'success': False, 'error': f"L'identifiant '{username}' existe déjà."}
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, role, is_active, is_online) VALUES (%s,%s,%s,%s,TRUE,FALSE) RETURNING id',
            (username, email, generate_password_hash(password), role)
        )
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f'✅ Utilisateur {username} ({role}) créé, id={new_id}')
        return {'success': True, 'message': f'Compte {username} créé', 'id': new_id}
    except Exception as e:
        logger.error(f'❌ Erreur create_user: {e}')
        return {'success': False, 'error': str(e)}


def set_user_active(user_id, is_active: bool):
    """Active ou désactive un utilisateur + force déconnexion si désactivé.
    Appelé par app.py /enable et /disable."""
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Erreur de connexion"}
    try:
        cursor = conn.cursor()
        if is_active:
            cursor.execute(
                "UPDATE users SET is_active = TRUE WHERE id = %s",
                (user_id,)
            )
        else:
            # Désactiver ET mettre is_online=FALSE pour déconnexion immédiate
            cursor.execute(
                "UPDATE users SET is_active = FALSE, is_online = FALSE WHERE id = %s",
                (user_id,)
            )
        conn.commit()
        cursor.close()
        conn.close()
        status = "activé" if is_active else "désactivé et déconnecté"
        logger.info(f"✅ Utilisateur {user_id} {status}")
        return {"success": True, "message": f"Utilisateur {status}"}
    except Exception as e:
        logger.error(f"❌ Erreur set_user_active: {e}")
        return {"success": False, "error": str(e)}


def save_sensitive_alert(user_id, user_name, user_role, question_text):
    """Sauvegarde une alerte question sensible dans sensitive_alerts.
    Retourne l'ID inséré (int) si succès, None sinon."""
    conn = get_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sensitive_alerts (user_id, user_name, user_role, question_text, created_at, seen)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
            RETURNING id
        """, (user_id, user_name, user_role, question_text))
        row = cursor.fetchone()
        alert_id = row[0] if row else None
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Alerte sensible sauvegardée pour {user_name} (id={alert_id})")
        return alert_id
    except Exception as e:
        logger.error(f"❌ Erreur save_sensitive_alert: {e}")
        return None

def get_unseen_sensitive_alerts():
    """Récupère les alertes sensibles non vues pour le dashboard admin."""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, user_id, user_name, user_role, question_text,
                   to_char(created_at, 'HH24:MI') as time_str,
                   created_at
            FROM sensitive_alerts
            WHERE seen = FALSE
            ORDER BY created_at DESC
            LIMIT 20
        """)
        alerts = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(a) for a in alerts]
    except Exception as e:
        logger.error(f"❌ Erreur get_unseen_sensitive_alerts: {e}")
        return []

def mark_alert_as_seen(alert_id):
    """Marque une alerte comme vue."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE sensitive_alerts SET seen = TRUE WHERE id = %s", (alert_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Erreur mark_alert_as_seen: {e}")
        return False

def get_real_connected_count():
    """Retourne le nombre d'utilisateurs vraiment connectés (last_seen < 5 min)."""
    conn = get_connection()
    if not conn:
        return 0
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE is_active = TRUE
            AND is_online = TRUE
            AND last_seen > NOW() - INTERVAL '5 minutes'
        """)
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"❌ Erreur get_real_connected_count: {e}")
        return 0

# ══════════════════════════════════════════════════════════════════
#  PANDAS & DATAFRAME
# ══════════════════════════════════════════════════════════════════

def get_production_data_df():
    """Retourne les données de production sous forme de DataFrame pandas"""
    try:
        engine = create_engine(SQLALCHEMY_URI)
        df = pd.read_sql('SELECT * FROM production ORDER BY date_mesure DESC LIMIT 200', engine)
        logger.info(f"✅ Production data loaded: {len(df)} rows")
        return df
    except Exception as e:
        logger.error(f"❌ get_production_data_df error: {e}")
        return None

def create_daily_activity_table():
    """Crée la table daily_activity si elle n'existe pas encore.
    Appelée au démarrage du serveur depuis app.py."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_activity (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                activity_date DATE NOT NULL DEFAULT CURRENT_DATE,
                UNIQUE(user_id, activity_date)
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Table daily_activity prête")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur création daily_activity: {e}")
        return False

def get_week_activity(offset=0):
    """
    Retourne le nombre d'utilisateurs actifs par jour pour la semaine demandée.
    Lit depuis daily_activity (présence réelle) — alimentée à chaque requête via update_last_seen.
    offset=0  → semaine courante (lundi → aujourd'hui)
    offset=-1 → semaine dernière (7 jours complets Lun→Dim)
    offset=-2 → il y a 2 semaines, etc.
    Résultat : { "days": ["Lun 12", "Mar 13", ...], "counts": [5, 12, 3, ...] }

    FIX : DATE_TRUNC('week', NOW()) en PostgreSQL tronque au DIMANCHE (convention US).
    On utilise DATE_TRUNC('week', NOW() + INTERVAL '1 day') - INTERVAL '1 day'
    pour obtenir le lundi de la semaine courante, quelle que soit la locale PostgreSQL.
    """
    conn = get_connection()
    if not conn:
        return {"days": [], "counts": []}
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # FIX : calcul du lundi réel (indépendant de la locale PostgreSQL)
        # DATE_TRUNC('week', d) peut donner dimanche selon la config du serveur.
        # La formule ci-dessous donne toujours le lundi ISO :
        #   lundi_semaine = date - (EXTRACT(ISODOW FROM date)::int - 1)
        # On l'applique sur NOW() décalé de (offset * 7 jours).
        cursor.execute("""
            WITH week_bounds AS (
                SELECT
                    (NOW()::date + (%s * 7)) - (EXTRACT(ISODOW FROM NOW()::date + (%s * 7))::int - 1)
                        AS week_monday
            )
            SELECT
                activity_date,
                COUNT(DISTINCT user_id) AS cnt
            FROM daily_activity, week_bounds
            WHERE
                activity_date >= week_monday
                AND activity_date <  week_monday + INTERVAL '7 days'
            GROUP BY activity_date
            ORDER BY activity_date
        """, (offset, offset))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        from datetime import datetime, date, timedelta

        # Construire un dict date → count depuis les résultats
        counts_by_date = {}
        for r in rows:
            d = r['activity_date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            counts_by_date[d] = int(r['cnt'])

        # Calculer le lundi de la semaine cible
        today = date.today()
        target_day = today + timedelta(weeks=offset)
        monday = target_day - timedelta(days=target_day.weekday())  # weekday() : 0=Lun

        if offset < 0:
            # Semaine passée → 7 jours complets Lun→Dim
            num_days = 7
        else:
            # Semaine courante → Lun → aujourd'hui seulement
            num_days = today.weekday() + 1  # weekday() : 0=Lun, donc +1 pour compter le jour actuel

        fr_labels = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']

        days, counts = [], []
        for i in range(num_days):
            d = monday + timedelta(days=i)
            label = f"{fr_labels[d.weekday()]} {d.day:02d}"
            days.append(label)
            counts.append(counts_by_date.get(d, 0))

        logger.info(f"✅ Activité semaine (offset={offset}): {list(zip(days, counts))}")
        return {"days": days, "counts": counts}

    except Exception as e:
        logger.error(f"❌ Erreur get_week_activity: {e}")
        return {"days": [], "counts": []}