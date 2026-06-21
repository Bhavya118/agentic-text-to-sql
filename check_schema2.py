import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])

for table_name, in tables:
    cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    col_names = [c[1] for c in cols]
    if "player_name" in col_names:
        print(f"\nFOUND player_name in table: {table_name}")
        print("All columns:", col_names)

conn.close()