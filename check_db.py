import sys
sys.path.insert(0, '.')
import DataBaseImacab

try:
    conn = DataBaseImacab.get_connection()
    cur = conn.cursor()
    
    # Lister les tables
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
    tables = cur.fetchall()
    print("=== TABLES DANS LA BASE ===")
    for t in tables:
        print(f"  - {t[0]}")
    
    print("\n=== NOMBRE DE LIGNES PAR TABLE ===")
    for t in tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM public."{t[0]}"')
            count = cur.fetchone()[0]
            print(f"  {t[0]}: {count} lignes")
        except Exception as e:
            print(f"  {t[0]}: ERREUR - {e}")
            conn.rollback()
    
    cur.close()
    conn.close()
    print("\nDiagnostic terminé.")
except Exception as e:
    print(f"ERREUR connexion: {e}")
