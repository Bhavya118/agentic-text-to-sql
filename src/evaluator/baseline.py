import time
import duckdb
from pathlib import Path
from openai import OpenAI
from config import GEMINI_API_KEY, LLM_MODEL
from src.common.schema_utils import get_raw_schema

client = OpenAI(api_key=GEMINI_API_KEY)


def call_llm(prompt: str, retries: int = 5, wait: int = 30) -> str:
    """Call OpenAI with automatic retry on errors."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if any(code in str(e) for code in ["429", "503", "rate_limit", "timeout"]):
                print(f"\n  API busy, waiting {wait}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait)
            else:
                raise
    raise Exception("OpenAI failed after all retries")


def run_baseline(question: str, db_path: Path, evidence: str = "") -> dict:
    """
    One-shot baseline: sends question + raw schema + evidence to LLM in a single prompt.
    No semantic context, no correction loop.
    """
    raw_schema = get_raw_schema(db_path)

    evidence_section = f"\nAdditional hint: {evidence}\n" if evidence else ""

    prompt = f"""You are an expert SQLite query writer.

Question: {question}
{evidence_section}
Database schema:
{raw_schema}

Rules:
- Write a single valid SQLite SQL query that answers the question.
- Always wrap column names containing spaces or special characters in double quotes.
- Use exact column and table names from the schema above — do not guess or abbreviate.
- Evidence hints may contain pseudo-code or shorthand notation (e.g. SUBTRACT(), DIVIDE(), AVG(x WHERE y)). Translate these into valid SQLite syntax — never copy pseudo-code function names directly into SQL.
- When evidence gives an explicit formula (e.g. "X = A / B"), follow the exact arithmetic structure given, including order of operations and which value is the numerator vs denominator.
- When the question asks to "list" or "show" a field, exclude rows where that field itself is NULL, unless explicitly asked to include them.
- When the question asks for a "rank" or "ranking", include an explicit rank/position column using RANK() OVER (...), not just an ORDER BY. Prefer RANK() over ROW_NUMBER() — RANK() gives tied values the same rank, which is almost always the intended meaning; only use ROW_NUMBER() if the question explicitly needs a unique sequential position even among ties.
- Order the columns in your SELECT clause to match the order the corresponding entities are mentioned or requested in the question — do not reorder them for readability, since column order is part of exact-match grading.
- Do not add a JOIN, table, or extra condition that isn't strictly required to answer the question — prefer the simplest query that satisfies the literal question over a more elaborate one, even if the elaborate one seems more thorough.
- Return ONLY the SQL query. No explanation, no markdown, no backticks."""
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