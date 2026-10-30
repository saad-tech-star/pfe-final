#!/usr/bin/env python
# ============================================================================
# INIT_DATABASE.PY - Initialiser la BD IMACAB
# ============================================================================

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, DECIMAL, Date, CheckConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash
from datetime import datetime
import traceback

DB_URL = 'postgresql://postgres:0123@localhost:5432/usine_cables'
engine = create_engine(DB_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# ============================================================================
# MODELS
# ============================================================================

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # directeur, responsable, medical, operateur
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatLog(Base):
    __tablename__ = 'chat_logs'
    id = Column(Integer, primary_key=True)
    question = Column(String, nullable=False)
    sql_generated = Column(String)
    success = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class BotMetadata(Base):
    __tablename__ = 'bot_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================================
# INITIALISATION
# ============================================================================

def init_database():
    """Crée les tables et insère les données de test"""
    
    try:
        print("🔄 Création des tables...")
        Base.metadata.create_all(engine)
        print("✅ Tables créées/vérifiées")
        
        # --- Insérer les utilisateurs de test ---
        session = Session()
        
        # Vérifier si les users existent déjà
        if session.query(User).filter_by(email='directeur@imacab.dh').first() is None:
            print("👤 Insertion des utilisateurs de test...")
            
            users = [
                User(
                    username='directeur_imacab',
                    email='directeur@imacab.dh',
                    password_hash=generate_password_hash('password123'),
                    role='directeur'
                ),
                User(
                    username='responsable_imacab',
                    email='responsable@imacab.dh',
                    password_hash=generate_password_hash('password123'),
                    role='responsable'
                ),
                User(
                    username='medical_imacab',
                    email='medical@imacab.dh',
                    password_hash=generate_password_hash('password123'),
                    role='medical'
                ),
                User(
                    username='operateur_imacab',
                    email='operateur@imacab.dh',
                    password_hash=generate_password_hash('password123'),
                    role='operateur'
                )
            ]
            
            session.add_all(users)
            session.commit()
            print(f"✅ {len(users)} utilisateurs créés")
            
            # Afficher les identifiants
            print("\n" + "="*60)
            print("👤 UTILISATEURS DE TEST (password: password123)")
            print("="*60)
            for user in users:
                print(f"  {user.role.upper():12} | {user.email:30} | {user.username}")
            print("="*60 + "\n")
        else:
            print("ℹ️  Les utilisateurs de test existent déjà")
            
        # --- Insérer les métadonnées par défaut ---
        if session.query(BotMetadata).filter_by(key='dictionnaire_metier').first() is None:
            print("⚙️ Insertion des métadonnées du bot (dictionnaire_metier, system_prompt)...")
            
            default_prompt_texte = """Tu es l'assistant expert de l'usine IMACAB (fabrication de câbles).
Tu réponds en français, de façon concise et professionnelle.

RÔLE DE L'UTILISATEUR : {role}
DROITS D'ACCÈS : {droits}

DONNÉES RÉELLES DANS LA BASE (utilise UNIQUEMENT ces valeurs pour répondre) :
{schema}

RÈGLES ABSOLUES :
1. Tu réponds TOUJOURS en texte simple. Pas de JSON, pas de SQL visible, pas de Markdown.
2. Si on te demande une valeur, cherche-la dans les exemples et donne la valeur EXACTE.
3. Si on te demande une liste, liste les valeurs réelles des exemples.
4. Si l'utilisateur n'a pas accès, refuse poliment en expliquant.
5. Si la donnée n'est pas dans les exemples, dis que tu ne disposes pas de cette formation.
6. Pour les analyses, explique en texte, puis propose un graphique.
7. Ne génère JAMAIS de JSON dans ce mode."""

            default_prompt_graphique = """Tu es l'assistant expert de l'usine IMACAB (fabrication de câbles).

RÔLE DE L'UTILISATEUR : {role}
DROITS D'ACCÈS : {droits}

STRUCTURE RÉELLE DE LA BASE AVEC DONNÉES D'EXEMPLES :
{schema}

MISSION : Générer un JSON de graphique basé sur une requête SQL précise et correcte.

RÈGLES ABSOLUES :
1. Réponds UNIQUEMENT avec un objet JSON valide. Zéro texte avant ou après.
2. Pas de balises Markdown (pas de ```json). Le JSON brut directement.
3. La requête SQL doit utiliser les VRAIS noms de tables et colonnes listés ci-dessus.
4. Toujours préfixer les tables avec le schéma : FROM public."nom_table"
5. Si l'utilisateur n'a pas accès → JSON : {{"erreur": "Accès refusé : [raison de refuse]"}}

FORMAT JSON EXACT (respecte cette structure) :
{{
  "sql": "SELECT col1, col2 FROM public.\\\"nom_table\\\" WHERE ... ORDER BY col1 LIMIT 100",
  "titre": "Titre lisible du graphique",
  "graph_type": "line" ou "bar" ou "pie" ou "scatter",
  "x_axis": "nom_colonne_axe_x",
  "y_axis": "nom_colonne_axe_y"
}}"""

            import json
            default_aliases = {
                "bobine": "unite_stockage"
            }
            
            meta_items = [
                BotMetadata(key='dictionnaire_metier', value=json.dumps(default_aliases)),
                BotMetadata(key='system_prompt_texte', value=default_prompt_texte),
                BotMetadata(key='system_prompt_graphique', value=default_prompt_graphique)
            ]
            session.add_all(meta_items)
            session.commit()
            print("✅ Métadonnées du bot initialisées")
        else:
            print("ℹ️  Les métadonnées du bot existent déjà")
        
        session.close()
        
        print("✨ Initialisation terminée avec succès !")
        return True
        
    except Exception as e:
        print(f"❌ ERREUR : {e}")
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     🏭 INITIALISATION BD - CHATBOT IMACAB               ║
    ║        Synchronisation des tables PostgreSQL             ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    init_database()
