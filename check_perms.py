import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import DataBaseImacab

conn = DataBaseImacab.get_connection()
cur = conn.cursor()
cur.execute('SELECT role, module, permission FROM permissions ORDER BY role, module')
rows = cur.fetchall()
print(f"Total: {len(rows)} lignes")
for r in rows:
    print(f"  {r[0]} | {r[1]} | {r[2]}")
cur.close()
conn.close()
