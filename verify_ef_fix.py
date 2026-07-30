import json
import sqlite3
from config import DATA_DIR
from src.evaluator.ex_checker import normalise_sql_quotes

db_path = DATA_DIR / "dev_databases" / "european_football_2" / "european_football_2.sqlite"

with open(DATA_DIR / "dev.json") as f:
    questions = json.load(f)

ef_questions = [q for q in questions if q["db_id"] == "european_football_2"]

conn = sqlite3.connect(str(db_path))

success = 0
failed = 0
failed_examples = []

for q in ef_questions:
    gold_sql = normalise_sql_quotes(q["SQL"])
    try:
        result = conn.execute(gold_sql).fetchall()
        success += 1
    except Exception as e:
        failed += 1
        if len(failed_examples) < 3:
            failed_examples.append({
                "question": q["question"],
                "error": str(e)
            })

conn.close()

print(f"Total questions: {len(ef_questions)}")
print(f"Gold SQL executes successfully: {success}")
print(f"Gold SQL still failing: {failed}")

if failed_examples:
    print("\nRemaining failures:")
    for ex in failed_examples:
        print(f"  Q: {ex['question']}")
        print(f"  Error: {ex['error']}")
        print()