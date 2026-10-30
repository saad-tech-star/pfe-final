"""
app.py — IMACAB Flask Backend (VERSION CORRIGÉE v3)

Corrections :
  1. ✅ Rôles corrigés : admin = is_admin True, directeur = consultation
  2. ✅ Login accepte JSON ET FormData
  3. ✅ Route PUT /api/admin/user/<id>/role ajoutée
  4. ✅ Route GET /api/admin/logs corrigée
  5. ✅ Route GET /api/admin/kpi/stats corrigée
  6. ✅ Timeout Ollama configuré
  7. ✅ Route GET /api/admin/activity/week lit le paramètre offset et le passe à la DB
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_from_directory, Response, stream_with_context
from flask_cors import CORS
from functools import wraps
from datetime import timedelta
import json
import os
import numpy as np
import logging
import queue
import threading
import DataBaseImacab
import ollamaAi
import db_inspector

# ── File d'attente SSE (partagée entre threads) ──────
_alert_listeners: list[queue.Queue] = []
_alert_listeners_lock = threading.Lock()

# ──────────────────────────────────────────────────────
#  LOGGING
# ──────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────
#  APP FLASK
# ──────────────────────────────────────────────────────
app = Flask(__name__, static_folder='imacab-react/build', static_url_path='')
CORS(app, supports_credentials=True, origins=['http://localhost:3000'])

app.secret_key = 'imacab_secret_key_2024_pfe'
app.config['PERMANENT_SESSION_LIFETIME']  = timedelta(minutes=60)
app.config['SESSION_PERMANENT']           = False
app.config['SESSION_COOKIE_SAMESITE']     = 'Lax'
app.config['SESSION_COOKIE_SECURE']       = False

# ──────────────────────────────────────────────────────
#  ENCODEUR JSON (numpy + datetime)
# ──────────────────────────────────────────────────────
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):   return int(obj)
        if isinstance(obj, np.floating):  return float(obj)
        if isinstance(obj, np.ndarray):   return obj.tolist()
        if hasattr(obj, 'isoformat'):     return obj.isoformat()
        return super().default(obj)

app.json_encoder = NumpyEncoder

# ──────────────────────────────────────────────────────
#  DÉCORATEURS
# ──────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api') or request.is_json:
                return jsonify({"error": "Non authentifié"}), 401
            return redirect(url_for('serve_react'))
        return f(*args, **kwargs)
    return decorated

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                if request.path.startswith('/api') or request.is_json:
                    return jsonify({"error": "Non authentifié"}), 401
                return redirect(url_for('serve_react'))
            if session.get('role') not in allowed_roles:
                return jsonify({"error": "Accès refusé."}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

# ✅ CORRECTION : admin_required vérifie is_admin depuis la session
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api') or request.is_json:
                return jsonify({"error": "Non authentifié"}), 401
            return redirect(url_for('serve_react'))
        # Admin ET directeur peuvent accéder au dashboard
        # Mais seulement admin peut modifier (vérifié dans chaque route)
        if not session.get('is_admin') and session.get('role') not in ('admin', 'directeur'):
            return jsonify({"error": "Accès administrateur requis."}), 403
        return f(*args, **kwargs)
    return decorated

# ── Push SSE vers tous les admins connectés ──────────
def _broadcast_alert(alert_payload: dict):
    """Envoie une alerte en temps réel à tous les listeners SSE."""
    data = json.dumps(alert_payload, default=str)
    dead = []
    with _alert_listeners_lock:
        for q in _alert_listeners:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _alert_listeners.remove(q)

# Admin seul (pas directeur) pour les opérations de modification
def admin_write_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Non authentifié"}), 401
        if not session.get('is_admin') and session.get('role') != 'admin':
            return jsonify({"error": "Modification réservée à l'administrateur."}), 403
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────────────────────
#  last_seen
# ──────────────────────────────────────────────────────
@app.before_request
def update_last_seen():
    if 'user_id' in session:
        try:
            user_id = session['user_id']
            DataBaseImacab.update_last_seen(user_id)

            # ✅ Vérifier si l'admin a forcé la déconnexion de cet utilisateur
            if DataBaseImacab.check_forced_logout(user_id):
                DataBaseImacab.set_user_online(user_id, False)
                session.clear()
                if request.path.startswith('/api') or request.is_json:
                    return jsonify({"error": "Session terminée par l'administrateur."}), 401
                return redirect(url_for('serve_react'))

            # ✅ Vérifier si l'utilisateur a été désactivé par l'admin
            user = DataBaseImacab.get_user_by_id(session['user_id'])
            if user and not user.get('is_active', True):
                DataBaseImacab.set_user_online(session['user_id'], False)
                session.clear()
                if request.path.startswith('/api') or request.is_json:
                    from flask import abort
                    abort(401)
                return redirect(url_for('serve_react'))
        except Exception:
            pass

# ──────────────────────────────────────────────────────
#  REACT — build
# ──────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path=''):
    build_dir = os.path.join(os.path.dirname(__file__), 'imacab-react', 'build')
    if path and os.path.exists(os.path.join(build_dir, path)):
        return send_from_directory(build_dir, path)
    index = os.path.join(build_dir, 'index.html')
    if os.path.exists(index):
        return send_from_directory(build_dir, 'index.html')
    return jsonify({"status": "Flask API running", "frontend": "http://localhost:3000"}), 200

# ──────────────────────────────────────────────────────
#  STATIC ASSETS (Logo, etc)
# ──────────────────────────────────────────────────────
@app.route('/static/<path:filename>')
def serve_original_static(filename):
    # Cherche d'abord dans le build React
    react_static = os.path.join(os.path.dirname(__file__), 'imacab-react', 'build', 'static')
    react_file = os.path.join(react_static, filename)
    if os.path.exists(react_file):
        return send_from_directory(react_static, filename)
    # Sinon dans le dossier static Flask
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    return send_from_directory(static_dir, filename)

# ──────────────────────────────────────────────────────
#  AUTH
# ──────────────────────────────────────────────────────
@app.route('/login', methods=['POST'])
def login():
    # ✅ CORRECTION : Support JSON ET FormData
    if request.is_json:
        data     = request.get_json()
        email    = data.get('email')
        password = data.get('password')
    else:
        email    = request.form.get('email')
        password = request.form.get('password')

    if not email or not password:
        return jsonify({"success": False, "error": "Email et mot de passe requis"}), 400

    user = DataBaseImacab.check_credentials(email, password)
    if user:
        session.permanent       = False
        session['user_id']      = user['id']
        session['username']     = user['username']
        session['email']        = user['email']
        session['role']         = user['role']
        session['is_admin']     = user.get('is_admin', user['role'] == 'admin')
        DataBaseImacab.set_user_online(user['id'], True)
        ip = request.remote_addr or '127.0.0.1'
        DataBaseImacab.log_login_attempt(user['id'], ip, True, 'Connexion réussie')
        logger.info(f"Connexion réussie: {email} [{user['role']}]")
        return jsonify({
            "success":  True,
            "username": user['username'],
            "email":    user['email'],
            "role":     user['role'],
            "is_admin": session['is_admin'],
        })
    else:
        ip = request.remote_addr or '127.0.0.1'
        DataBaseImacab.log_login_attempt(None, ip, False, f'Échec: {email}')
        logger.warning(f"Échec connexion: {email}")
        return jsonify({"success": False, "error": "Identifiants incorrects"}), 401

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    user_id = session.get('user_id')
    if user_id:
        try:
            DataBaseImacab.set_user_online(user_id, False)
        except Exception:
            pass
    session.clear()
    return jsonify({"success": True})

# ── Route pour vérifier la session ──────────────────
@app.route('/api/me', methods=['GET'])
def get_me():
    """Vérifie si l'utilisateur est connecté — accessible à tous."""
    if 'user_id' not in session:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "user_id":  session.get('user_id'),
        "username": session.get('username'),
        "email":    session.get('email'),
        "role":     session.get('role'),
        "is_admin": session.get('is_admin'),
    })

# ──────────────────────────────────────────────────────
#  ADMIN — DASHBOARD
# ──────────────────────────────────────────────────────
@app.route('/api/admin/dashboard/data')
@admin_required
def get_admin_dashboard_data():
    try:
        data = DataBaseImacab.get_dashboard_data(
            user_role=session.get('role'),
            is_admin=session.get('is_admin')
        )
        return jsonify(data)
    except Exception as e:
        logger.error(f"Erreur dashboard: {e}")
        return jsonify({"error": str(e)}), 500

# ──────────────────────────────────────────────────────
#  ADMIN — ALERTS (SENSITIVE)
# ──────────────────────────────────────────────────────
@app.route('/api/admin/alerts/sensitive', methods=['GET'])
@admin_required
def get_sensitive_alerts():
    try:
        alerts = DataBaseImacab.get_unseen_alerts()
        for a in alerts:
            if 'created_at' in a and a['created_at']:
                a['created_at'] = a['created_at'].isoformat()
        return jsonify({"alerts": alerts})
    except Exception as e:
        logger.error(f"Erreur get_sensitive_alerts: {e}")
        return jsonify({"error": str(e), "alerts": []}), 500

@app.route('/api/admin/alerts/sensitive/<int:alert_id>/seen', methods=['POST'])
@admin_write_required
def mark_alert_seen_endpoint(alert_id):
    try:
        success = DataBaseImacab.mark_alert_seen(alert_id)
        return jsonify({"success": success})
    except Exception as e:
        logger.error(f"Erreur mark_alert_seen: {e}")
        return jsonify({"error": str(e)}), 500

# ── SSE — stream d'alertes en temps réel ─────────────
@app.route('/api/admin/alerts/stream')
@role_required(['admin', 'directeur', 'responsable'])
def alert_stream():
    """
    Server-Sent Events : chaque admin connecté reçoit les alertes
    en temps réel dès qu'un utilisateur pose une question bloquée.
    """
    q = queue.Queue(maxsize=50)
    with _alert_listeners_lock:
        _alert_listeners.append(q)
    logger.info(f"[SSE] Nouveau listener connecté ({len(_alert_listeners)} total)")

    def generate():
        # Heartbeat initial pour confirmer la connexion
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    # Attente 25s max → envoyer un heartbeat pour garder la connexion
                    data = q.get(timeout=25)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    yield "data: {\"type\":\"heartbeat\"}\n\n"
        except GeneratorExit:
            pass
        finally:
            with _alert_listeners_lock:
                if q in _alert_listeners:
                    _alert_listeners.remove(q)
            logger.info(f"[SSE] Listener déconnecté ({len(_alert_listeners)} restants)")

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':   'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection':      'keep-alive',
        }
    )

# ──────────────────────────────────────────────────────
#  ADMIN — STATS / LOGS
# ──────────────────────────────────────────────────────
@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_users():
    try:
        users = DataBaseImacab.get_all_users()
        return jsonify({"users": users})
    except Exception as e:
        logger.error(f"Erreur get_users: {e}")
        return jsonify({"error": str(e), "users": []}), 500

@app.route('/api/admin/users/online', methods=['GET'])
@login_required
def get_online_users():
    try:
        online = DataBaseImacab.get_online_users()
        return jsonify({"online": online, "total_online": len(online)})
    except Exception as e:
        return jsonify({"error": str(e), "online": [], "total_online": 0}), 500

@app.route('/api/admin/user/<int:user_id>/force-logout', methods=['POST'])
@admin_write_required
def force_logout_user(user_id):
    """Force la déconnexion réelle d'un utilisateur depuis la map de supervision."""
    try:
        result = DataBaseImacab.force_logout_user(user_id)
        logger.info(f"[ADMIN] Force-logout user {user_id} par {session.get('username')}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur force_logout_user: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ✅ CORRECTION : admin seul peut changer les rôles
@app.route('/api/admin/user/<int:user_id>/role', methods=['PUT'])
@admin_write_required
def update_user_role(user_id):
    try:
        data     = request.get_json()
        new_role = data.get('role')
        if new_role not in ('admin', 'directeur', 'responsable', 'medical', 'operateur'):
            return jsonify({"error": "Rôle invalide"}), 400
        result = DataBaseImacab.update_user_role(user_id, new_role)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur update_user_role: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/users/create', methods=['POST'])
@admin_write_required
def create_user_route():
    try:
        username = request.form.get('username', '').strip()
        prenom   = request.form.get('prenom', '').strip()
        nom      = request.form.get('nom', '').strip()
        password = request.form.get('password', '').strip()
        role     = request.form.get('role', '').strip()

        if not all([username, password, role]):
            return jsonify({'error': 'username, password et role sont obligatoires'}), 400

        result = DataBaseImacab.create_user(
            username=username,
            email=f"{username}@imacab.dh",
            password=password,
            role=role,
        )
        if not result.get('success'):
            return jsonify(result), 400
        logger.info(f"[ADMIN] Compte '{username}' créé par {session.get('username')}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur create_user: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/user/<int:user_id>/enable', methods=['POST'])
@admin_write_required
def enable_user(user_id):
    try:
        result = DataBaseImacab.set_user_active(user_id, True)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/user/<int:user_id>/disable', methods=['POST'])
@admin_write_required
def disable_user(user_id):
    try:
        result = DataBaseImacab.set_user_active(user_id, False)
        logger.info(f"[ADMIN] Utilisateur {user_id} désactivé par {session.get('username')}")
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/user/<int:user_id>/delete', methods=['DELETE'])
@admin_write_required
def delete_user(user_id):
    try:
        result = DataBaseImacab.delete_user(user_id)
        logger.info(f"[ADMIN] Utilisateur {user_id} supprimé par {session.get('username')}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur delete_user: {e}")
        return jsonify({"error": str(e)}), 500

# ──────────────────────────────────────────────────────
#  ADMIN — LOGS
# ──────────────────────────────────────────────────────
@app.route('/api/admin/logs')
@admin_required
def get_logs():
    try:
        logs = DataBaseImacab.get_login_logs()
        return jsonify({"logs": logs})
    except Exception as e:
        logger.error(f"Erreur get_logs: {e}")
        return jsonify({"logs": [], "error": str(e)}), 500

# ──────────────────────────────────────────────────────
#  ADMIN — KPI
# ──────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────
#  ADMIN — ACTIVITÉ SEMAINE (données réelles par jour)
# ──────────────────────────────────────────────────────
@app.route('/api/admin/activity/week')
@admin_required
def get_week_activity():
    """
    Retourne le nombre de connexions réussies par jour pour la semaine demandée.
    Paramètre GET : offset (int, défaut=0)
      0  → semaine courante (lundi → aujourd'hui)
     -1  → semaine dernière (lundi → dimanche complet)
     -2  → il y a 2 semaines, etc.
    """
    try:
        offset = request.args.get('offset', 0, type=int)
        # Sécurité : on n'autorise pas les offsets dans le futur
        if offset > 0:
            offset = 0
        activity = DataBaseImacab.get_week_activity(offset=offset)
        return jsonify(activity)
    except Exception as e:
        logger.error(f"Erreur get_week_activity: {e}")
        return jsonify({"days": [], "counts": [], "error": str(e)}), 500

@app.route('/api/admin/kpi/stats')
@admin_required
def get_kpi_stats():
    try:
        stats = DataBaseImacab.get_kpi_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Erreur kpi_stats: {e}")
        # Retourner des valeurs par défaut pour éviter dashboard vide
        return jsonify({
            "total_users":    0,
            "active_users":   0,
            "total_chats":    0,
            "total_messages": 0,
            "success_rate":   0,
            "online_users":   0,
        })

# ──────────────────────────────────────────────────────

#  ADMIN — PERMISSIONS RBAC
# ──────────────────────────────────────────────────────
@app.route('/api/permissions', methods=['GET', 'POST'])
@admin_required
def api_permissions():
    if request.method == 'GET':
        try:
            perms = DataBaseImacab.get_permissions()
            return jsonify(perms)
        except Exception as e:
            return jsonify([]), 500

    elif request.method == 'POST':
        # ✅ Admin seul peut modifier les permissions
        if not session.get('is_admin') and session.get('role') != 'admin':
            return jsonify({'error': 'Modification réservée à l\'administrateur.'}), 403
        data       = request.get_json()
        role       = data.get('role')
        module     = data.get('module')
        permission = data.get('permission')
        if not (role and module and permission):
            return jsonify({'error': 'Paramètres manquants'}), 400
        ok = DataBaseImacab.set_permission(role, module, permission)
        if ok:
            try:
                ollamaAi.notify_permission_change(role, module, permission)
            except Exception as e:
                logger.warning(f"Notification IA échouée: {e}")
            return jsonify({'success': True})
        return jsonify({'error': 'Erreur enregistrement permission'}), 500

# ──────────────────────────────────────────────────────
#  ADMIN — MODULES RBAC DYNAMIQUES
# ──────────────────────────────────────────────────────
@app.route('/api/permissions/modules', methods=['GET'])
@admin_required
def api_permissions_modules():
    """Retourne la liste distincte des modules depuis la table permissions.
    Le frontend l'utilise pour construire dynamiquement les colonnes
    de la matrice RBAC — plus besoin de toucher au code quand on ajoute une table.
    """
    try:
        modules = DataBaseImacab.get_distinct_modules()
        return jsonify({"modules": modules})
    except Exception as e:
        logger.error(f"Erreur get_modules: {e}")
        return jsonify({"modules": ["PROD.", "MAINT.", "VENTES", "MÉD."]})

@app.route('/api/permissions/modules/add', methods=['POST'])
@admin_required
def api_add_module():
    """Ajoute un nouveau module dans la matrice RBAC pour tous les rôles.
    Body JSON : { "module": "QUALITE" }
    Toutes les permissions sont initialisées à '✗', l'admin règle ensuite case par case.
    """
    if not session.get('is_admin') and session.get('role') != 'admin':
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    data   = request.get_json()
    module = (data.get('module') or '').strip().upper()
    if not module:
        return jsonify({'error': 'Nom du module manquant'}), 400
    ok = DataBaseImacab.add_module_to_permissions(module)
    if ok:
        return jsonify({'success': True, 'module': module})
    return jsonify({'error': 'Erreur lors de l\'ajout du module'}), 500


@app.route('/api/permissions/modules/delete', methods=['POST'])
@admin_write_required
def api_delete_module():
    """Supprime un module de la matrice RBAC — efface TOUTES les règles liées.
    Body JSON : { "module": "QUALITE" }
    """
    data   = request.get_json()
    module = (data.get('module') or '').strip()
    if not module:
        return jsonify({'error': 'Nom du module manquant'}), 400
    # Interdire la suppression des modules système de base
    PROTECTED = {'PROD.', 'MAINT.', 'VENTES', 'MÉD.', 'MED.'}
    if module.upper() in PROTECTED:
        return jsonify({'error': f'Le module "{module}" est protégé et ne peut pas être supprimé.'}), 403
    ok = DataBaseImacab.delete_module_from_permissions(module)
    if ok:
        logger.info(f"[ADMIN] Module '{module}' supprimé par {session.get('username')}")
        return jsonify({'success': True, 'module': module})
    return jsonify({'error': 'Erreur lors de la suppression du module'}), 500

# ──────────────────────────────────────────────────────
#  INSPECTION DB — 4 routes
# ──────────────────────────────────────────────────────

@app.route('/api/inspect/tables', methods=['GET'])
@login_required
def inspect_tables():
    """
    Analyse automatique de toutes les tables :
    nom, nb colonnes, types, nb lignes, taille.
    Rôle admin/directeur/responsable uniquement.
    """
    role = session.get('role', '')
    if role not in ('admin', 'directeur'):
        return jsonify({"error": "Accès réservé aux rôles admin et directeur."}), 403
    try:
        result = db_inspector.analyze_tables(include_internal=(role == 'admin'))
        logger.info(f"[INSPECT] tables par {session.get('username')} ({role})")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur inspect_tables: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/inspect/relations', methods=['GET'])
@login_required
def inspect_relations():
    """
    Détecte les clés primaires, étrangères et génère le graphe de relations.
    Paramètre GET optionnel : table_a=xxx&table_b=yyy pour filtrer 2 tables.
    """
    role = session.get('role', '')
    if role not in ('admin', 'directeur'):
        return jsonify({"error": "Accès réservé aux rôles admin et directeur."}), 403
    try:
        table_a = request.args.get('table_a')
        table_b = request.args.get('table_b')

        if table_a and table_b:
            result = db_inspector.get_relation_between(table_a, table_b)
        else:
            result = db_inspector.get_relations(include_internal=(role == 'admin'))

        logger.info(f"[INSPECT] relations par {session.get('username')} ({role})")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur inspect_relations: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/inspect/nulls', methods=['GET'])
@login_required
def inspect_nulls():
    """
    Détecte les valeurs NULL dans toutes les tables accessibles.
    Paramètre GET optionnel : tables=ventes,production (liste séparée par virgule)
    """
    role = session.get('role', '')
    if role not in ('admin', 'directeur'):
        return jsonify({"error": "Accès réservé aux rôles admin et directeur."}), 403
    try:
        tables_param = request.args.get('tables')
        tables = [t.strip() for t in tables_param.split(',')] if tables_param else None
        result = db_inspector.detect_nulls(
            tables=tables,
            include_internal=(role == 'admin')
        )
        logger.info(f"[INSPECT] nulls par {session.get('username')} ({role})")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur inspect_nulls: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/inspect/duplicates', methods=['GET'])
@login_required
def inspect_duplicates():
    """
    Détecte les doublons dans toutes les tables accessibles.
    Paramètre GET optionnel : tables=ventes,production
    """
    role = session.get('role', '')
    if role not in ('admin', 'directeur'):
        return jsonify({"error": "Accès réservé aux rôles admin et directeur."}), 403
    try:
        tables_param = request.args.get('tables')
        tables = [t.strip() for t in tables_param.split(',')] if tables_param else None
        result = db_inspector.detect_duplicates(
            tables=tables,
            include_internal=(role == 'admin')
        )
        logger.info(f"[INSPECT] duplicates par {session.get('username')} ({role})")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur inspect_duplicates: {e}")
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────
#  CHAT — IA
# ──────────────────────────────────────────────────────
@app.route('/chat', methods=['POST'])
@login_required
def chat():
    try:
        data    = request.get_json()
        message = data.get('message', '').strip() if data else ''

        if not message:
            return jsonify({"type": "text", "text": "Votre message est vide."}), 400

        user_role = session.get('role', 'operateur')
        logger.info(f"[{user_role.upper()}] {session.get('username')}: {message[:80]}")

        # ── Intercept appels inspection directs depuis le dashboard ──
        if message.startswith('__inspect__:'):
            action = message.replace('__inspect__:', '').strip()
            if user_role not in ('admin', 'directeur'):
                return jsonify({"type": "text", "text": "🔒 Accès réservé aux rôles admin et directeur."}), 403
            result = ollamaAi._handle_inspect(action, {}, user_role)
            logger.info(f"[INSPECT via chat] {action} par {session.get('username')} ({user_role})")
            return jsonify(result)

        # ✅ RBAC vérifie le message ORIGINAL (pas le contexte enrichi)
        # Sinon un contexte comme "production" bloque les questions médicales

        # ✅ VÉRIFICATION RBAC IMMÉDIATE — avant tout appel à l'IA
        # Si accès refusé : réponse instantanée + alerte admin
        rbac_error = ollamaAi._check_rbac(message, user_role)
        if rbac_error:
            # Déclencher l'alerte admin si c'est du staff médical
            alert_id = ollamaAi._detect_sensitive_question(message, user_role)
            logger.warning(f"[RBAC BLOQUÉ] {user_role} | {message[:80]}")

            # ── Broadcast SSE en temps réel ──────────────────
            try:
                alert_payload = {
                    "id":            alert_id,
                    "user_id":       session.get('user_id'),
                    "user_name":     session.get('username'),
                    "user_role":     user_role,
                    "question_text": message,
                    "time_str":      __import__('datetime').datetime.now().strftime('%H:%M:%S'),
                    "seen":          False,
                }
                _broadcast_alert(alert_payload)
                logger.info(f"[SSE] Alerte broadcastée: {session.get('username')} ({user_role})")
            except Exception as sse_err:
                logger.warning(f"[SSE] Erreur broadcast: {sse_err}")

            return jsonify({"type": "text", "text": rbac_error})

        # ✅ CORRECTION : lire l'ANCIEN message AVANT de sauvegarder le nouveau
        last_message = session.get('last_user_message', '')
        session['last_user_message'] = message
        session.modified = True

        # Contexte conversationnel — uniquement pour l'IA, PAS pour le RBAC
        msg_lower = message.lower()
        # Mots qui signalent que le message fait référence à la question précédente
        # ✅ CORRECTION : On retire 'sous forme', 'en graphe', 'en graphique', 'en graph',
        # 'le', 'la', 'les' — ces mots déclenchaient à tort l'injection du contexte,
        # ce qui polluait la détection du nouveau type de graphique demandé.
        ref_words = [
            'ça', 'ca', 'cela', 'ceci',
            'maintenant', 'aussi', 'pareil', 'idem', 'même chose'
        ]
        is_contextual = any(w in msg_lower for w in ref_words) and len(message) < 80

        # ✅ CORRECTION : Ne jamais injecter le contexte si le nouveau message
        # contient déjà un type de graphique explicite — sinon l'ancien type
        # (ex: "pie chart") présent dans le contexte écrase le nouveau (ex: "histogramme").
        graph_type_words = [
            'pie', 'bar', 'histogramme', 'camembert', 'line', 'courbe',
            'chart', 'graphique', 'graphe', 'diagramme', 'barre', 'barres'
        ]
        contains_graph_type = any(w in msg_lower for w in graph_type_words)

        enriched = (
            f"{message} (contexte : l'utilisateur parlait de '{last_message}')"
            if is_contextual and last_message and not contains_graph_type
            else message
        )

        result = ollamaAi.generer_sql(user_msg=enriched, original_msg=message, user_role=user_role)

        # CAS 1 : graphique
        if isinstance(result, dict) and 'sql' in result:
            sql      = result.get('sql')
            raw_data = DataBaseImacab.executer_requete_ia(sql)
            if not raw_data or isinstance(raw_data, dict):
                return jsonify({"type": "text", "text": "Aucune donnée disponible pour ce graphique."})
            return jsonify({
                "type":       "graphique",
                "response":   raw_data,
                "sql":        sql,
                "titre":      result.get('titre', ''),
                "graph_type": result.get('graph_type', 'bar'),
                "x_axis":     result.get('x_axis', ''),
                "y_axis":     result.get('y_axis', ''),
            })

        # CAS 1b : inspection DB
        if isinstance(result, dict) and result.get('type') == 'inspect':
            return jsonify(result)

        # CAS 2 : accès refusé
        if isinstance(result, dict) and 'erreur' in result:
            return jsonify({"type": "text", "text": result['erreur']})

        # CAS 3 : texte normal
        return jsonify({"type": "text", "text": str(result)})

    except Exception as e:
        logger.error(f"Erreur chat: {e}")
        return jsonify({"type": "text", "text": f"Erreur serveur: {str(e)}"}), 500

# ──────────────────────────────────────────────────────
#  SYNC EXCEL
# ──────────────────────────────────────────────────────
@app.route('/sync', methods=['GET', 'POST'])
@role_required(['directeur', 'responsable', 'admin'])
def sync():
    try:
        import etl_pipeline
        result = etl_pipeline.sync_excel_to_db()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur sync: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ──────────────────────────────────────────────────────
#  ERROR HANDLERS
# ──────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Page non trouvée"}), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Erreur serveur: {e}")
    return jsonify({"error": "Erreur serveur interne"}), 500

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"error": "Accès refusé"}), 403

# ──────────────────────────────────────────────────────
#  DÉMARRAGE
# ──────────────────────────────────────────────────────
if __name__ == '__main__':
    logger.info("=== Démarrage IMACAB ===")
    with app.app_context():
        # ✅ Crée la table daily_activity si elle n'existe pas
        try:
            DataBaseImacab.create_forced_logouts_table()
        except Exception as e:
            logger.warning(f"forced_logouts init: {e}")

        try:
            DataBaseImacab.create_daily_activity_table()
        except Exception as e:
            logger.warning(f"daily_activity init: {e}")

        try:
            import etl_pipeline
            result = etl_pipeline.sync_excel_to_db()
            if result.get('success'):
                logger.info(f"Sync Excel OK: {len(result.get('tables_updated', []))} tables")
            else:
                logger.warning(f"Sync Excel avec erreurs: {result.get('errors', [])}")
        except Exception as e:
            logger.warning(f"Sync Excel non disponible: {e}")

    is_electron = os.environ.get('ELECTRON_RUN') == '1'
app.run(debug=not is_electron, host='0.0.0.0', port=5000, threaded=True, use_reloader=not is_electron)