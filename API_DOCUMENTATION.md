# 🏭 IMACAB Chatbot - Guide Complet d'Utilisation

## 📋 Table des matières
1. [Installation & Configuration](#installation)
2. [Routes Disponibles](#routes)
3. [ETL Pipeline](#etl)
4. [Sécurité RBAC](#securite)
5. [Exemples d'Utilisation](#exemples)
6. [Tests](#tests)

---

## 🚀 Installation & Configuration {#installation}

### 1️⃣ Initialiser la BD

```bash
cd "c:\Users\CePC\Desktop\chatbot imacab"
python init_database.py
```

**Utilisateurs créés :**
```
Rôle         | Email                      | Username
─────────────┼────────────────────────────┼──────────────────
Directeur    | directeur@imacab.dh        | directeur_imacab
Responsable  | responsable@imacab.dh      | responsable_imacab
Médical      | medical@imacab.dh          | medical_imacab
Opérateur    | operateur@imacab.dh        | operateur_imacab
```
**Mot de passe pour tous : `password123`**

### 2️⃣ Lancer l'application

```bash
python app.py
```

Ouvrir : `http://localhost:5000`

### 3️⃣ Charger les données Excel

```bash
curl -X GET http://localhost:5000/sync \
  -H "Content-Type: application/json" \
  --user directeur@imacab.dh:password123
```

---

## 📡 Routes Disponibles {#routes}

### ✅ AUTHENTIFICATION

| Route | Méthode | Description |
|-------|---------|-------------|
| `/login` | GET/POST | Connexion utilisateur |
| `/logout` | GET | Déconnexion |

### 💬 CHATBOT

| Route | Méthode | Auth | Rôles | Description |
|-------|---------|------|-------|-------------|
| `/chat` | POST | ✅ | Tous | Envoyer un message au chatbot |
| `/chat` | POST | ✅ | Tous | (Voir détails ci-dessous) |

**Requête JSON :**
```json
{
  "message": "Quelle est la vitesse moyenne aujourd'hui?"
}
```

**Réponse :**
```json
{
  "response": [
    {"vitesse_ligne": 45.2, "date_mesure": "2026-04-16T08:00:00"},
    {"vitesse_ligne": 47.5, "date_mesure": "2026-04-16T08:05:00"}
  ],
  "sql": "SELECT vitesse_ligne, date_mesure FROM public.production_cables...",
  "type": "graphique",
  "columns": ["vitesse_ligne", "date_mesure"]
}
```

### 🔄 ETL - SYNCHRONISATION EXCEL

| Route | Méthode | Description | Accès |
|-------|---------|-------------|-------|
| `/sync` | POST | Synchroniser Excel vers BD | 🔒 Directeur/Responsable |
| `/sync-status` | GET | Stats de synchronisation | 🔒 Directeur/Responsable |

**Exemple :**
```bash
curl -X POST http://localhost:5000/sync \
  -H "Content-Type: application/json" \
  -d '{"file_path": "imacab_data.xlsx"}'
```

**Réponse :**
```json
{
  "success": true,
  "timestamp": "2026-04-16T10:30:00.123456",
  "tables_updated": [
    {"table": "production_cables", "rows": 1000, "status": "✅ SUCCÈS"},
    {"table": "maintenance_machines", "rows": 50, "status": "✅ SUCCÈS"},
    {"table": "ventes_usine", "rows": 200, "status": "✅ SUCCÈS"}
  ],
  "errors": [],
  "stats": {
    "production_cables": 1000,
    "maintenance_machines": 50,
    "ventes_usine": 200
  }
}
```

### 🛠️ MAINTENANCE

| Route | Méthode | Description | Accès |
|-------|---------|-------------|-------|
| `/maintenance` | GET | Lister tâches | 🔒 Directeur/Responsable/Médical |
| `/update_maintenance/<id>` | PUT | Mettre à jour tâche | 🔒 Directeur/Responsable/Médical |

**Exemple - Lister les tâches non effectuées :**
```bash
curl -X GET "http://localhost:5000/maintenance?effectue=false"
```

**Réponse :**
```json
{
  "success": true,
  "filter": "effectue=false",
  "tasks": [
    {
      "id": 1,
      "machine_id": "M-01",
      "action": "Vidange Huile",
      "date_prevue": "2026-04-20",
      "effectue": false
    }
  ],
  "count": 1
}
```

**Exemple - Marquer une tâche comme effectuée :**
```bash
curl -X PUT "http://localhost:5000/update_maintenance/1" \
  -H "Content-Type: application/json" \
  -d '{"effectue": true}'
```

### 📊 VISUALISATION

| Route | Méthode | Description | Accès |
|-------|---------|-------------|-------|
| `/chart-production` | GET | Données production Plotly | ✅ Tous |
| `/chart-maintenance-status` | GET | Graphique maintenance | ✅ Tous |
| `/chart-sales` | GET | Graphique ventes | 🔒 Directeur/Responsable |

---

## ETL Pipeline {#etl}

### Fonctionnement

1. **Lecture Excel**
   - Onglet `production` → Table `production_cables`
   - Onglet `maintenaince` → Table `maintenance_machines`
   - Onglet `ventes` → Table `ventes_usine`

2. **Normalisation des données**
   ```python
   - Conversion dates → DATETIME/DATE
   - Conversion effectue → BOOLEAN
   - Conversion montant_dh → DECIMAL
   ```

3. **Chargement PostgreSQL**
   ```python
   df.to_sql('table_name', engine, if_exists='replace', index=False)
   ```

### Code d'appel

```python
from etl_pipeline import sync_excel_to_db

result = sync_excel_to_db('imacab_data.xlsx')
print(result)
```

---

## 🔐 Sécurité RBAC {#securite}

### Modèle d'accès

```
┌─────────────────┬─────────────────┬──────────────────┬─────────────────┐
│ Rôle            │ Production      │ Maintenance      │ Ventes          │
├─────────────────┼─────────────────┼──────────────────┼─────────────────┤
│ Directeur       │ ✅ Lecture      │ ✅ Lecture/Écriture│ ✅ Lecture      │
│ Responsable     │ ✅ Lecture      │ ✅ Lecture/Écriture│ ✅ Lecture      │
│ Médical         │ ❌ Non          │ ✅ Lecture/Écriture│ ❌ Non          │
│ Opérateur       │ ✅ Lecture      │ ❌ Non           │ ❌ Non          │
└─────────────────┴─────────────────┴──────────────────┴─────────────────┘
```

### Décorateurs

```python
@role_required(['directeur', 'responsable'])
def sync_excel():
    # Seuls directeur et responsable peuvent appeler cette route
    pass
```

### Vérification dans Ollama

```python
# ollamaAi.generer_sql(user_msg, user_role='operateur')
# Refuse automatiquement les questions sur ventes_usine pour l'opérateur
```

---

## 📝 Exemples d'Utilisation {#exemples}

### 1️⃣ Opérateur demande la vitesse

```
Question : "Quelle est la vitesse moyenne des 5 derniers jours?"

Réponse :
✅ Accès autorisé (Production = OK pour Opérateur)
Type : Graphique Plotly
Données : vitesse_ligne par date
```

### 2️⃣ Opérateur demande les ventes

```
Question : "Montre-moi les ventes du mois dernier"

Réponse :
🚫 Accès refusé
Message : "🔒 Accès refusé : Vous n'avez pas les permissions pour accéder à ventes_usine"
```

### 3️⃣ Directeur demande les ventes

```
Question : "Total des ventes en avril?"

Réponse :
✅ Accès autorisé (Directeur = Tous)
Type : Graphique barres
Données : total par jour
```

### 4️⃣ Synchroniser l'Excel (Directeur uniquement)

```bash
POST /sync
Authorization: directeur@imacab.dh:password123

Réponse :
{
  "success": true,
  "tables_updated": [...],
  "stats": {production_cables: 1000, ...}
}
```

### 5️⃣ Mettre à jour une tâche de maintenance (Responsable)

```bash
PUT /update_maintenance/2
Authorization: responsable@imacab.dh:password123

Body: {"effectue": true}

Réponse:
{
  "success": true,
  "message": "✅ Tâche 2 mise à jour",
  "task": {
    "id": 2,
    "machine_id": "M-02",
    "action": "Diagnostic",
    "effectue": true
  }
}
```

---

## 🧪 Tests {#tests}

### Test authentification

```bash
# ❌ Sans authentification
curl http://localhost:5000/maintenance
# → Redirection login

# ✅ Avec authentification
curl -X GET http://localhost:5000/maintenance \
  -H "Cookie: session=..."
```

### Test RBAC - Opérateur refuse ventes

```bash
LOGIN: operateur@imacab.dh / password123

Question: "Ventes totales?"

Réponse: 🔒 Accès refusé
```

### Test RBAC - Directeur access ventes

```bash
LOGIN: directeur@imacab.dh / password123

Question: "Ventes totales?"

Réponse: ✅ Graphique avec données
```

### Test sync ETL

```bash
LOGIN: directeur@imacab.dh / password123

POST /sync

Vérifier:
- Tables mises à jour
- Nombre de lignes corrects
- Pas d'erreurs
```

---

## 🔧 Troubleshooting

### Erreur : "Module ModuleNotFoundError: No module named 'openpyxl'"
```bash
pip install openpyxl
```

### Erreur : "ConnectionError - PostgreSQL non accessible"
```bash
# Vérifier que PostgreSQL est lancé
# Vérifier les credentials : postgres:0123@localhost:5432
```

### Erreur : "Unauthorized 403"
```bash
# Vérifier le rôle de l'utilisateur
# GET /sync nécessite 'directeur' ou 'responsable'
```

---

## 📚 Fichiers Clés

| Fichier | Rôle |
|---------|------|
| `app.py` | Application Flask + routes |
| `ollamaAi.py` | IA (Ollama) + sécurité RBAC |
| `etl_pipeline.py` | Synchronisation Excel → PostgreSQL |
| `init_database.py` | Initialisation BD + users |
| `DataBaseImacab.py` | Connexion PostgreSQL + requêtes |
| `imacab_data.xlsx` | Données source (3 onglets) |

---

## ✨ Résumé des Améliorations

✅ Pipeline ETL complet : Excel → PostgreSQL
✅ Sécurité RBAC stricte : 4 rôles, 3 tables
✅ Chatbot sécurisé : Refused les questions non autorisées
✅ Maintenance : CRUD complet pour les tâches
✅ Visualisation : Graphiques Plotly dynamiques
✅ Authentification : Sessions Flask sécurisées
✅ Logs : Traçabilité complète des opérations

---

**Développé pour IMACAB - Usine de Fabrication de Câbles 🏭**
