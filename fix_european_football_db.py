import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

print("Before fix:")
cols = conn.execute("PRAGMA table_info('Player')").fetchall()
print("Player columns:", [c[1] for c in cols])

# Add missing columns to Player from Player_old
print("\nAdding missing columns to Player table...")

alterations = [
    "ALTER TABLE Player ADD COLUMN player_name TEXT",
    "ALTER TABLE Player ADD COLUMN player_fifa_api_id BIGINT",
    "ALTER TABLE Player ADD COLUMN birthday TEXT",
    "ALTER TABLE Player ADD COLUMN weight INTEGER"
]

for sql in alterations:
    try:
        conn.execute(sql)
        print(f"  ✓ {sql}")
    except Exception as e:
        print(f"  ✗ Already exists or error: {e}")

# Copy values from Player_old to Player
print("\nCopying values from Player_old...")
conn.execute("""
    UPDATE Player
    SET 
        player_name = (SELECT player_name FROM Player_old WHERE Player_old.player_api_id = Player.player_api_id),
        player_fifa_api_id = (SELECT player_fifa_api_id FROM Player_old WHERE Player_old.player_api_id = Player.player_api_id),
        birthday = (SELECT birthday FROM Player_old WHERE Player_old.player_api_id = Player.player_api_id),
        weight = (SELECT weight FROM Player_old WHERE Player_old.player_api_id = Player.player_api_id)
""")
conn.commit()

print("\nAfter fix:")
cols = conn.execute("PRAGMA table_info('Player')").fetchall()
print("Player columns:", [c[1] for c in cols])

# Verify
sample = conn.execute("SELECT player_api_id, player_name, height FROM Player LIMIT 3").fetchall()
print("\nSample rows:", sample)

# Test the gold SQL that was failing
try:
    result = conn.execute("SELECT player_name FROM Player ORDER BY height DESC LIMIT 1").fetchone()
    print(f"\nGold SQL test — tallest player: {result}")
    print("Fix successful!")
except Exception as e:
    print(f"Still failing: {e}")

conn.close()