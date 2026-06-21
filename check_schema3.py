import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

cols = conn.execute("PRAGMA table_info('Player')").fetchall()
print("Player full info:", cols)

# Try running the actual gold SQL to see if it even works
try:
    result = conn.execute("SELECT player_name FROM Player ORDER BY height DESC LIMIT 1").fetchall()
    print("Gold SQL result:", result)
except Exception as e:
    print("Gold SQL ERROR:", e)

conn.close()