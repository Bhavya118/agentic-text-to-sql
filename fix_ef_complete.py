import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

print("Copying all data from Player_old into Player...")

# Get Player_old columns
old_cols = conn.execute("PRAGMA table_info('Player_old')").fetchall()
print(f"Player_old columns: {[c[1] for c in old_cols]}")

# Insert all rows from Player_old into Player
conn.execute("""
    INSERT INTO Player (player_api_id, player_name, player_fifa_api_id, birthday, height, weight)
    SELECT player_api_id, player_name, player_fifa_api_id, birthday, height, weight
    FROM Player_old
""")
conn.commit()

# Verify
count = conn.execute("SELECT COUNT(*) FROM Player").fetchone()[0]
print(f"\nPlayer rows after fix: {count}")

sample = conn.execute(
    "SELECT player_api_id, player_name, height FROM Player LIMIT 3"
).fetchall()
print(f"Sample rows: {sample}")

# Test the gold SQL that was failing before
result = conn.execute(
    "SELECT player_name FROM Player ORDER BY height DESC LIMIT 1"
).fetchone()
print(f"\nTallest player: {result}")
print("\nFix complete!")

conn.close()