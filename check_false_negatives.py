import duckdb
from config import DATA_DIR
from src.evaluator.ex_checker import normalise_sql_quotes, normalise_result

db_path = str(DATA_DIR / "dev_databases" / "superhero" / "superhero.sqlite")

cases = [
    {
        "name": "missing weight",
        "agent_sql": "SELECT full_name FROM superhero WHERE weight_kg = 0 OR weight_kg IS NULL;",
        "gold_sql": "SELECT DISTINCT full_name FROM superhero WHERE full_name IS NOT NULL AND (weight_kg IS NULL OR weight_kg = 0)"
    },
]

conn = duckdb.connect(db_path)

for case in cases:
    print(f"=== {case['name']} ===")
    agent_sql = normalise_sql_quotes(case["agent_sql"])
    gold_sql  = normalise_sql_quotes(case["gold_sql"])

    agent_result = conn.execute(agent_sql).fetchall()
    gold_result  = conn.execute(gold_sql).fetchall()

    print(f"Agent rows: {len(agent_result)}")
    print(f"Gold rows:  {len(gold_result)}")

    agent_norm = normalise_result(agent_result)
    gold_norm  = normalise_result(gold_result)

    print(f"Sets equal: {agent_norm == gold_norm}")

    only_in_agent = agent_norm - gold_norm
    only_in_gold  = gold_norm - agent_norm

    print(f"Only in agent ({len(only_in_agent)}):", list(only_in_agent)[:5])
    print(f"Only in gold  ({len(only_in_gold)}):", list(only_in_gold)[:5])
    print()

conn.close()