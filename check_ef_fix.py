import sqlite3
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"
conn = sqlite3.connect(str(db_path))

# Check row counts
player_count = conn.execute("SELECT COUNT(*) FROM Player").fetchone()[0]
player_old_count = conn.execute("SELECT COUNT(*) FROM Player_old").fetchone()[0]
print(f"Player rows: {player_count}")
print(f"Player_old rows: {player_old_count}")

# Check if player_api_id values overlap
overlap = conn.execute("""
    SELECT COUNT(*) FROM Player p
    JOIN Player_old po ON p.player_api_id = po.player_api_id
""").fetchone()[0]
print(f"Matching player_api_id between Player and Player_old: {overlap}")

# Check sample from both tables
print("\nPlayer sample:")
print(conn.execute("SELECT * FROM Player LIMIT 3").fetchall())

print("\nPlayer_old sample:")
print(conn.execute("SELECT player_api_id, player_name FROM Player_old LIMIT 3").fetchall())

conn.close()