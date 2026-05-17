import sqlite3
import json
from pathlib import Path
from config import DATA_DIR, MAX_SAMPLE_ROWS, MAX_FREQ_VALUES


def get_table_names(conn: sqlite3.Connection) -> list[str]:
    """Return all user table names in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def get_column_info(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    """Return column metadata for a given table."""
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    columns = []
    for row in rows:
        columns.append({
            "cid":         row[0],
            "name":        row[1],
            "type":        row[2],
            "notnull":     bool(row[3]),
            "default":     row[4],
            "primary_key": bool(row[5])
        })
    return columns


def get_foreign_keys(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    """Return foreign key relationships for a given table."""
    rows = conn.execute(f"PRAGMA foreign_key_list('{table_name}')").fetchall()
    fks = []
    for row in rows:
        fks.append({
            "from_column":  row[3],
            "to_table":     row[2],
            "to_column":    row[4]
        })
    return fks


def get_sample_values(conn: sqlite3.Connection, table_name: str, column_name: str) -> list:
    """Return up to MAX_SAMPLE_ROWS non-null sample values for a column."""
    try:
        rows = conn.execute(
            f"SELECT DISTINCT \"{column_name}\" FROM \"{table_name}\" "
            f"WHERE \"{column_name}\" IS NOT NULL LIMIT {MAX_SAMPLE_ROWS}"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def get_value_distribution(conn: sqlite3.Connection, table_name: str, column_name: str) -> list[dict]:
    """Return top N most frequent values and their counts for a column."""
    try:
        rows = conn.execute(
            f"SELECT \"{column_name}\", COUNT(*) as cnt "
            f"FROM \"{table_name}\" "
            f"WHERE \"{column_name}\" IS NOT NULL "
            f"GROUP BY \"{column_name}\" "
            f"ORDER BY cnt DESC "
            f"LIMIT {MAX_FREQ_VALUES}"
        ).fetchall()
        return [{"value": r[0], "count": r[1]} for r in rows]
    except Exception:
        return []


def get_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    """Return total row count for a table."""
    try:
        result = conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        return result[0]
    except Exception:
        return -1


def profile_database(db_path: Path) -> dict:
    """
    Main function. Profiles an entire SQLite database and returns
    a structured dictionary ready for JSON serialisation.
    """
    conn = sqlite3.connect(str(db_path))
    db_name = db_path.stem

    profile = {
        "database_name": db_name,
        "tables": []
    }

    table_names = get_table_names(conn)

    for table_name in table_names:
        columns     = get_column_info(conn, table_name)
        foreign_keys = get_foreign_keys(conn, table_name)
        row_count   = get_row_count(conn, table_name)

        table_profile = {
            "table_name":   table_name,
            "row_count":    row_count,
            "columns":      [],
            "foreign_keys": foreign_keys
        }

        for col in columns:
            col_name = col["name"]
            samples  = get_sample_values(conn, table_name, col_name)
            dist     = get_value_distribution(conn, table_name, col_name)

            table_profile["columns"].append({
                "name":        col_name,
                "type":        col["type"],
                "primary_key": col["primary_key"],
                "notnull":     col["notnull"],
                "sample_values":      samples,
                "value_distribution": dist
            })

        profile["tables"].append(table_profile)

    conn.close()
    return profile

def save_profile(profile: dict, output_dir: Path) -> Path:
    """Save the profile dictionary as a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{profile['database_name']}_raw_profile.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    return output_path

if __name__ == "__main__":
    from config import SEMANTIC_DIR

    db_path = DATA_DIR / "dev_databases" / "california_schools" / "california_schools.sqlite"
    
    print("Profiling database...")
    profile = profile_database(db_path)

    print(f"Database : {profile['database_name']}")
    print(f"Tables   : {len(profile['tables'])}")
    for t in profile["tables"]:
        print(f"  - {t['table_name']} ({t['row_count']} rows, {len(t['columns'])} columns)")

    output_path = save_profile(profile, SEMANTIC_DIR)
    print(f"\nProfile saved to: {output_path}")