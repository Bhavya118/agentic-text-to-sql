import json
import duckdb
from config import DATA_DIR
from src.evaluator.ex_checker import normalise_sql_quotes

db_path = str(DATA_DIR / "dev_databases" / "california_schools" / "california_schools.sqlite")

with open(DATA_DIR / "dev.json") as f:
    questions = json.load(f)

ca_questions = [q for q in questions if q["db_id"] == "california_schools"][:5]

conn = duckdb.connect(db_path)

for q in ca_questions:
    gold_sql = normalise_sql_quotes(q["SQL"])
    print(f"Question : {q['question']}")
    print(f"Gold SQL : {gold_sql}")
    try:
        result = conn.execute(gold_sql).fetchall()
        print(f"Gold result: {result[:3]}")
    except Exception as e:
        print(f"Gold SQL ERROR: {e}")
    print()

conn.close()