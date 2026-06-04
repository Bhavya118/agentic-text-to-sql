import json
from pathlib import Path
from config import RESULTS_DIR

# Load the latest run
latest = sorted(RESULTS_DIR.iterdir())[-1]
print(f"Analysing run: {latest.name}\n")

total = 0
baseline_match = 0
agent_match = 0
baseline_exec_fail = 0
agent_exec_fail = 0
agent_corrected = 0
initially_failed = 0

per_db = []

for checkpoint_file in sorted(latest.glob("*_checkpoint.json")):
    with open(checkpoint_file) as f:
        data = json.load(f)

    results = data["results"]
    if not results:
        continue

    db_name = checkpoint_file.stem.replace("_checkpoint", "")

    db_total        = len(results)
    db_base_match   = sum(1 for r in results if r.get("baseline_match", False))
    db_agent_match  = sum(1 for r in results if r.get("agent_match", False))
    db_base_fail    = sum(1 for r in results if not r.get("baseline_success", True))
    db_agent_fail   = sum(1 for r in results if not r.get("agent_success", True))
    db_corrected    = sum(1 for r in results if r.get("self_corrected", False))
    db_init_failed  = sum(1 for r in results if len(r.get("error_history", [])) > 0)

    per_db.append({
        "db":                  db_name,
        "total":               db_total,
        "baseline_ex":         round(db_base_match / db_total * 100, 1),
        "agent_ex":            round(db_agent_match / db_total * 100, 1),
        "improvement":         round((db_agent_match - db_base_match) / db_total * 100, 1),
        "self_correction_rate": round(db_corrected / db_init_failed * 100, 1) if db_init_failed > 0 else 0.0
    })

    total              += db_total
    baseline_match     += db_base_match
    agent_match        += db_agent_match
    baseline_exec_fail += db_base_fail
    agent_exec_fail    += db_agent_fail
    agent_corrected    += db_corrected
    initially_failed   += db_init_failed

print("PER DATABASE RESULTS:")
print(f"{'Database':<30} {'N':>5} {'Base%':>7} {'Agent%':>7} {'Impr%':>7} {'SCR%':>7}")
print("-" * 65)
for db in per_db:
    print(f"{db['db']:<30} {db['total']:>5} {db['baseline_ex']:>7} {db['agent_ex']:>7} {db['improvement']:>7} {db['self_correction_rate']:>7}")

print(f"\nAGGREGATE:")
print(f"Total questions     : {total}")
print(f"Baseline EX         : {round(baseline_match / total * 100, 2)}%")
print(f"Agent EX            : {round(agent_match / total * 100, 2)}%")
print(f"Improvement         : +{round((agent_match - baseline_match) / total * 100, 2)}%")
print(f"Baseline exec fails : {baseline_exec_fail} ({round(baseline_exec_fail / total * 100, 1)}%)")
print(f"Agent exec fails    : {agent_exec_fail} ({round(agent_exec_fail / total * 100, 1)}%)")
print(f"Self-correction rate: {round(agent_corrected / initially_failed * 100, 1) if initially_failed > 0 else 0}%")