# 🏭 IMACAB Chatbot - Version 2.0 Production-Ready

> **Chatbot intelligent pour usine de fabrication de câbles avec sécurité RBAC, ETL Pipeline et visualisation interactive**

## 📊 Vue d'ensemble

IMACAB est une application web fullstack qui permet aux employés d'une usine de câbles d'interroger les données de production en langage naturel grâce à une IA générative (Ollama/Mistral).

### ✨ Nouvelles fonctionnalités

- ✅ **ETL Pipeline** : Synchronisation Excel → PostgreSQL
- ✅ **Sécurité RBAC** : 4 rôles, 3 niveaux de contrôle d'accès
- ✅ **Chatbot sécurisé** : Refuse les questions non autorisées  
- ✅ **Gestion Maintenance** : CRUD des tâches avec statuts
- ✅ **Visualisations** : Graphiques Plotly interactifs
- ✅ **Documentation complète** : API, exemples, troubleshooting

---

## 🚀 Démarrage Rapide

### Prérequis

- Python 3.10+
- PostgreSQL 12+
- Ollama (modèle Mistral)

### 3 étapes pour lancer

```bash
# 1. Initialiser la base de données
python init_database.py

# 2. Tester l'intégration
python test_integration.py

# 3. Lancer l'application
python app.py
```

Puis ouvrir : **http://localhost:5000**

### Utilisateurs de test

```
Email                    Password    Rôle
─────────────────────────────────────────────
directeur@imacab.dh     password123 Directeur
responsable@imacab.dh   password123 Responsable
operateur@imacab.dh     password123 Opérateur
medical@imacab.dh       password123 Médical
```

---

## 📁 Structure du projet

```
chatbot imacab/
├── app.py                      # Application Flask (modifiée)
├── ollamaAi.py                 # IA avec sécurité RBAC (modifiée)
├── etl_pipeline.py             # Pipeline ETL Excel→PostgreSQL (nouveau)
├── init_database.py            # Initialisation BD (nouveau)
├── test_integration.py         # Tests (nouveau)
├── quickstart.py               # Démarrage rapide (nouveau)
├── DataBaseImacab.py           # Connexion BD
├── requirements.txt            # Dépendances (modifié)
├── imacab_data.xlsx            # Données sources (3 onglets)
├── API_DOCUMENTATION.md        # Documentation API (nouveau)
├── RESUME_MODIFICATIONS.md     # Résumé des changements (nouveau)
├── README.md                   # Ce fichier
├── templates/
│   ├── index.html
│   └── login.html
└── static/
    └── [CSS, JS]
```

---

## 🔐 Sécurité RBAC

### Matrice d'accès

| Rôle | Production | Maintenance | Ventes |
|------|-----------|-------------|--------|
| **Directeur** | ✅ Lecture | ✅ RW | ✅ Lecture |
| **Responsable** | ✅ Lecture | ✅ RW | ✅ Lecture |
| **Médical** | ❌ | ✅ RW | ❌ |
| **Opérateur** | ✅ Lecture | ❌ | ❌ |

### Implémentation multi-niveaux

1. **Routes Flask** : Décorateur `@role_required(['directeur'])`
2. **Chatbot IA** : Vérification avant génération SQL
3. **Sessions** : Stockage et vérification du rôle

---

## 🔄 ETL Pipeline

### Flux de synchronisation

```
imacab_data.xlsx
    ├─ onglet "production"     → table production_cables
    ├─ onglet "maintenaince"   → table maintenance_machines
    └─ onglet "ventes"         → table ventes_usine
```

### Code d'utilisation

```python
from etl_pipeline import sync_excel_to_db

# Synchroniser l'Excel
result = sync_excel_to_db('imacab_data.xlsx')

# Afficher les résultats
print(result['tables_updated'])
print(result['stats'])
```

### Ou via API

```bash
POST /sync
Authorization: Bearer token_directeur
```

---

## 💬 Chatbot Sécurisé

### Exemple : Opérateur

```
Q: "Vitesse moyenne?" 
✅ AUTORISÉ - Données production accessible

Q: "Total des ventes?"
🚫 REFUSÉ - "Accès refusé : données réservées"
```

### Exemple : Directeur

```
Q: "Vitesse moyenne?"
✅ AUTORISÉ

Q: "Total des ventes?"
✅ AUTORISÉ

Q: "Tâches de maintenance?"
✅ AUTORISÉ
```

---

## 📡 Routes API Principales

### Routes sécurisées (authentication + RBAC)

```
POST   /sync                      ← Directeur/Responsable
GET    /sync-status              ← Directeur/Responsable
GET    /maintenance              ← Directeur/Responsable/Médical
PUT    /update_maintenance/<id>  ← Directeur/Responsable/Médical
GET    /chart-sales              ← Directeur/Responsable
```

### Routes authentifiées

```
POST   /chat                      ← Tous (authentifiés)
GET    /chart-production         ← Tous
GET    /chart-maintenance-status ← Tous
```

### Routes publiques

```
GET    /login
POST   /login
GET    /logout
```

---

## 📊 Visualisations

Graphiques Plotly interactifs :

- **Production** : Vitesse + Tension par timestamp
- **Maintenance** : Statut des tâches (camembert)
- **Ventes** : Chiffre d'affaires par jour (ligne)

---

## 🧪 Tests

### Vérifier l'intégration

```bash
python test_integration.py
```

Vérifie :
- ✅ Tous les imports
- ✅ Connexion PostgreSQL
- ✅ Lecture Excel
- ✅ Fichiers locaux

### Tester les droits RBAC

```python
# Avec opérateur
curl -X GET /maintenance -H "Cookie: user_role=operateur"
# ❌ Accès refusé

# Avec directeur
curl -X GET /maintenance -H "Cookie: user_role=directeur"
# ✅ OK
```

---

## 📚 Documentation

### Complète

Voir **`API_DOCUMENTATION.md`** pour :
- Tous les endpoints detaillés
- Exemples cURL
- Exemples JSON
- Cas d'usage par rôle
- Troubleshooting

### Résumé des modifications

Voir **`RESUME_MODIFICATIONS.md`** pour :
- Fichiers créés/modifiés
- Architecture complète
- Guide démarrage
- Notes importantes

---

## 🛠️ Installation des dépendances

```bash
pip install -r requirements.txt
```

Dépendances clés :
- Flask 3.0.0
- PostgreSQL (psycopg2)
- Pandas + numpy (traitement données)
- SQLAlchemy (ORM)
- Ollama (IA générative)
- Plotly (visualisations)

---

## ⚙️ Configuration

### 1. PostgreSQL

```python
# DataBaseImacab.py
DB_CONFIG = {
    "database": "usine_cables",
    "user": "postgres",
    "password": "0123",
    "port": "5432",
    "host": "localhost"
}
```

### 2. Flask

```python
# app.py
app.secret_key = 'imacab_secret_key_2024_pfe'  # À changer en prod
app.run(debug=True, port=5000)
```

### 3. Ollama

```bash
# Lancer Ollama avant de démarrer l'app
ollama serve
# Dans une autre session : ollama pull mistral
```

---

## 🐛 Troubleshooting

### PostgreSQL non accessible

```
Error: could not connect to database server
Solution: 
- Vérifier que PostgreSQL est lancé
- Vérifier credentials : postgres:0123@localhost:5432
```

### Ollama non accessible

```
Error: No module named 'ollama'
Solution:
- pip install ollama
- ollama serve
```

### Excel non trouvé

```
Error: FileNotFoundError: imacab_data.xlsx
Solution:
- Vérifier que imacab_data.xlsx existe au même niveau que app.py
```

### Accès refusé 403

```
Error: Unauthorized 403
Solution:
- Vérifier le rôle de l'utilisateur
- POST /sync nécessite directeur ou responsable
```

---

## 📝 Fichiers Clés

### Code applicatif

| Fichier | Rôle |
|---------|------|
| `app.py` | Routes Flask principales |
| `ollamaAi.py` | IA + sécurité RBAC |
| `etl_pipeline.py` | ETL Excel→PostgreSQL |
| `DataBaseImacab.py` | BD + requêtes |

### Configuration

| Fichier | Contenu |
|---------|---------|
| `requirements.txt` | Dépendances pip |
| `init_database.py` | Création tables + users test |
| `init_db.sql` | Script BD brut |

### Documentation

| Fichier | Type |
|---------|------|
| `API_DOCUMENTATION.md` | Documentation complète API |
| `RESUME_MODIFICATIONS.md` | Résumé changements |
| `README.md` | Ce fichier |

---

## 🚀 Améliorations Futures (Optionnel)

```
☐ Cache Redis (perfs graphiques)
☐ WebSocket (notifications temps réel)
☐ Export PDF (rapports)
☐ Audit trail (logs complets)
☐ 2FA (authentification forte)
☐ GraphQL (alternative REST)
☐ Dashboard admin
☐ Tests unitaires
☐ CI/CD (GitHub Actions)
☐ Docker (containerization)
```

---

## 📞 Support

### Documentation

- **API** : `API_DOCUMENTATION.md`
- **Modifications** : `RESUME_MODIFICATIONS.md`
- **Démarrage** : `quickstart.py`

### Tests

```bash
python test_integration.py  # Tester l'intégration
python quickstart.py        # Démarrage guidé
```

---

## 📄 License

Projet IMACAB - Développement PFE 2024-2026

---

## ✨ Résumé

**IMACAB v2.0** est une application production-ready avec :

- ✅ ETL Pipeline complet
- ✅ Sécurité RBAC multi-niveaux
- ✅ Chatbot IA intelligent et sécurisé
- ✅ Gestion maintenance intégrée
- ✅ Visualisations interactives
- ✅ Documentation complète
- ✅ Tests d'intégration

Tous les fichiers sont prêts. Lancez `python init_database.py` puis `python app.py` pour commencer ! 🚀

---

**Développé pour l'usine IMACAB - Fabrication de Câbles 🏭**
