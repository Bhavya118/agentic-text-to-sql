import json
import sqlite3
import time
import duckdb
from pathlib import Path
from groq import Groq
from config import GEMINI_API_KEY, LLM_MODEL

client = Groq(api_key=GEMINI_API_KEY)


def call_llm(prompt: str, retries: int = 5, wait: int = 15) -> str:
    """Call Groq with automatic retry on errors."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if any(code in str(e) for code in ["429", "503", "UNAVAILABLE", "rate_limit"]):
                print(f"\n  API busy, waiting {wait}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait)
            else:
                raise
    raise Exception("Groq failed after all retries")


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


def run_baseline(question: str, db_path: Path) -> dict:
    """
    One-shot baseline: sends question + raw schema to LLM in a single prompt.
    No semantic context, no correction loop.
    """
    raw_schema = get_raw_schema(db_path)

    prompt = f"""You are an expert SQL writer for SQLite databases.

Question: {question}

Database schema:
{raw_schema}

Write a single valid SQLite SQL query that answers the question.
Return ONLY the SQL query. No explanation, no markdown, no backticks."""

    sql = call_llm(prompt)

    if sql.startswith("```"):
        sql = sql.split("```")[1]
        if sql.startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()

    try:
        conn   = duckdb.connect(str(db_path))
        result = conn.execute(sql).fetchall()
        conn.close()
        return {
            "sql":     sql,
            "result":  result,
            "success": True,
            "error":   None
        }
    except Exception as e:
        return {
            "sql":     sql,
            "result":  None,
            "success": False,
            "error":   str(e)
        }


if __name__ == "__main__":
    from config import DATA_DIR

    db_path  = DATA_DIR / "dev_databases" / "california_schools" / "california_schools.sqlite"
    question = "What is the highest average SAT math score among all schools?"

    print(f"Question: {question}\n")
    result = run_baseline(question, db_path)
    print(f"SQL     : {result['sql']}")
    print(f"Success : {result['success']}")
    print(f"Result  : {result['result']}")