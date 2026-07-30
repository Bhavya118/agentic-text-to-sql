import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

# Add id column to Player
try:
    conn.execute("ALTER TABLE Player ADD COLUMN id INTEGER")
    print("Added id column to Player")
except Exception as e:
    print(f"id column already exists: {e}")

# Copy id values from Player_old
conn.execute("""
    UPDATE Player
    SET id = (
        SELECT id FROM Player_old 
        WHERE Player_old.player_api_id = Player.player_api_id
    )
""")
conn.commit()

# Verify
sample = conn.execute(
    "SELECT id, player_api_id, player_name FROM Player LIMIT 3"
).fetchall()
print(f"Sample with id: {sample}")

null_count = conn.execute(
    "SELECT COUNT(*) FROM Player WHERE id IS NULL"
).fetchone()[0]
print(f"Rows with NULL id: {null_count}")

conn.close()
print("Done.")