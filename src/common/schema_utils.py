import re
import sqlite3
from pathlib import Path


def find_columns(db_path: Path, column_name: str) -> list[str]:
    """
    Return 'table(column)' strings for every table that actually has a column
    matching column_name (case-insensitive). Used to give Node D's critic
    deterministic ground truth about where a column really lives, instead of
    relying on it to correctly parse/guess from a raw DuckDB error message.
    """
    conn   = sqlite3.connect(str(db_path))
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    target  = column_name.lower()
    matches = []
    for table_name in tables:
        cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        for col in cols:
            if col[1].lower() == target:
                matches.append(f"{table_name}({col[1]})")

    conn.close()
    return matches


def extract_missing_columns(error_msg: str) -> list[str]:
    """
    Best-effort, dependency-free extraction of column names that a DuckDB or
    SQLite error message complains are missing/unresolvable. Not exhaustive —
    only handles the "column not found" family of errors, which is the case
    find_columns() can actually resolve deterministically.
    """
    patterns = [
        r'[Cc]olumn\s+"([^"]+)"',
        r'no such column:\s*([\w."]+)',
        r'[Bb]inder [Ee]rror:.*?column\s+([\w."]+)',
    ]
    found = []
    for pattern in patterns:
        found.extend(re.findall(pattern, error_msg))

    cleaned = []
    for name in found:
        col = name.strip('"').split(".")[-1]
        if col and col not in cleaned:
            cleaned.append(col)
    return cleaned


def find_duplicate_columns(db_path: Path) -> dict[str, list[str]]:
    """
    Return {column_name: [table_names]} for column names that appear
    (case-insensitively) on more than one table, EXCLUDING primary keys and
    declared foreign-key linkage columns — those are expected/intentional
    join keys, not semantic ambiguity.

    This targets the specific failure mode found in the 2026-07-30 ablation
    run: Node A silently pointed the SQL generator at 'Examination.Diagnosis'
    instead of 'Patient.Diagnosis' in thrombosis_prediction — both columns
    genuinely exist, so this isn't a hallucination, it's a same-name
    collision across unrelated tables. Node A/B need an explicit warning to
    disambiguate rather than picking whichever table's description reads
    closest to the question.
    """
    conn   = sqlite3.connect(str(db_path))
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if not r[0].startswith("sqlite_")
    ]

    # Columns that participate in a declared FK relationship (on either side)
    # are expected to repeat by name across tables — exclude them.
    fk_occurrences = set()
    for table_name in tables:
        for fk in conn.execute(f"PRAGMA foreign_key_list('{table_name}')").fetchall():
            from_column, to_table = fk[3], fk[2]
            fk_occurrences.add((table_name.lower(), from_column.lower()))
            fk_occurrences.add((to_table.lower(), from_column.lower()))

    by_name = {}
    for table_name in tables:
        cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        for col in cols:
            col_name = col[1]
            key      = col_name.lower()
            is_pk    = bool(col[5])

            if key == "id" or len(key) <= 2 or is_pk:
                continue
            if (table_name.lower(), key) in fk_occurrences:
                continue

            entry = by_name.setdefault(key, {"display": col_name, "tables": []})
            entry["tables"].append(table_name)

    conn.close()
    return {
        v["display"]: v["tables"]
        for v in by_name.values()
        if len(v["tables"]) > 1
    }


def format_duplicate_columns(duplicates: dict[str, list[str]]) -> str:
    """Render duplicate-column warnings as a prompt-ready block. Empty string if none."""
    if not duplicates:
        return ""
    lines = [
        f"  - '{col}' exists on multiple tables: {', '.join(tables)} — "
        f"make sure you reference it from the table that actually matches the question's intent, not just the first match."
        for col, tables in duplicates.items()
    ]
    return (
        "Schema ambiguity warning — these column names exist identically on more than one table "
        "(this is a real collision, not a typo):\n" + "\n".join(lines)
    )


def get_raw_schema(db_path: Path) -> str:
    """
    Extract raw schema (table and column names only) from a SQLite database.
    No descriptions, no sample values, no semantic context.
    """
    conn   = sqlite3.connect(str(db_path))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    schema_lines = []
    for (table_name,) in tables:
        cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        col_defs = ", ".join(f"{c[1]} {c[2]}" for c in cols)
        schema_lines.append(f"Table: {table_name} ({col_defs})")

    conn.close()
    return "\n".join(schema_lines)
