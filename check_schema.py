import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

cols = conn.execute("PRAGMA table_info('Player')").fetchall()
print("Player columns:", [c[1] for c in cols])

conn.close()