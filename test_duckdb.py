import sqlite3
import duckdb
from config import DATA_DIR

db_path = DATA_DIR / "dev_databases" / "california_schools" / "california_schools.sqlite"

# ── Part 1: Read schema via sqlite3 (for profiling) ──────────────────────────
print("=== sqlite3 connection (for profiling) ===")
conn_sqlite = sqlite3.connect(str(db_path))

tables = conn_sqlite.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()

print(f"Tables found: {len(tables)}")
for t in tables:
    table_name = t[0]
    rows = conn_sqlite.execute(f"SELECT * FROM '{table_name}' LIMIT 2").fetchall()
    print(f"\n  Table: {table_name}")
    print(f"  Sample rows: {rows[:1]}")

conn_sqlite.close()

# ── Part 2: Execute SQL via DuckDB (for evaluation) ──────────────────────────
print("\n=== DuckDB connection (for evaluation) ===")
conn_duck = duckdb.connect(str(db_path))
result = conn_duck.execute("SELECT COUNT(*) FROM schools").fetchone()
print(f"Row count in schools table via DuckDB: {result[0]}")
conn_duck.close()

print("\nAll connection tests passed.")