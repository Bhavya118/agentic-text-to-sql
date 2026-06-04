import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
from config import DATA_DIR, RESULTS_DIR, SEMANTIC_DIR, MAX_CORRECTIONS
from src.evaluator.baseline import run_baseline
from src.evaluator.ex_checker import check_execution_accuracy
from src.agent.graph import build_agent
from src.agent.state import AgentState


def load_bird_questions(db_name: str, limit: int = None) -> list[dict]:
    """
    Load questions from BIRD dev.json for a specific database.
    """
    dev_json_path = DATA_DIR / "dev.json"
    with open(dev_json_path, "r", encoding="utf-8") as f:
        all_questions = json.load(f)

    db_questions = [q for q in all_questions if q["db_id"] == db_name]

    if limit:
        db_questions = db_questions[:limit]

    return db_questions


def run_agent_on_question(agent, question: str, db_name: str, db_path: Path) -> dict:
    """Run the full agent on a single question."""
    initial_state = {
        "question":               question,
        "db_name":                db_name,
        "db_path":                str(db_path),
        "retrieved_context":      "",
        "generated_sql":          "",
        "execution_result":       None,
        "execution_error":        None,
        "execution_success":      False,
        "error_history":          [],
        "correction_instruction": None,
        "attempt_number":         1
    }

    final_state = agent.invoke(initial_state)

    return {
        "sql":             final_state["generated_sql"],
        "success":         final_state["execution_success"],
        "attempts":        final_state["attempt_number"],
        "error_history":   final_state.get("error_history", []),
        "result":          final_state.get("execution_result")
    }


def evaluate_database(db_name: str, limit: int = None) -> dict:
    """
    Run baseline and agent on all questions for one database.
    Returns per-question results and aggregate metrics.
    """
    db_path   = DATA_DIR / "dev_databases" / db_name / f"{db_name}.sqlite"
    questions = load_bird_questions(db_name, limit)

    if not questions:
        print(f"  No questions found for {db_name}")
        return {}

    print(f"\n  {db_name}: {len(questions)} questions")

    agent   = build_agent()
    results = []

    for q in tqdm(questions, desc=f"  Evaluating {db_name}"):
        question = q["question"]
        gold_sql = q["SQL"]
        q_id     = q.get("question_id", q.get("id", "unknown"))

        # ── Run baseline ──────────────────────────────────────────────────────
        baseline_out = run_baseline(question, db_path)
        baseline_ex  = check_execution_accuracy(
            baseline_out["sql"], gold_sql, db_path
        ) if baseline_out["success"] else {"match": False, "note": "execution failed"}

        time.sleep(5)  # rate limit

        # ── Run agent ─────────────────────────────────────────────────────────
        agent_out = run_agent_on_question(agent, question, db_name, db_path)
        agent_ex  = check_execution_accuracy(
            agent_out["sql"], gold_sql, db_path
        ) if agent_out["success"] else {"match": False, "note": "execution failed"}

        time.sleep(5)  # rate limit

        # ── Self-correction tracking ──────────────────────────────────────────
        # Did it fail on attempt 1 but succeed later?
        corrected = (
            agent_out["attempts"] > 1 and agent_out["success"]
        )

        results.append({
            "question_id":       q_id,
            "question":          question,
            "gold_sql":          gold_sql,
            "baseline_sql":      baseline_out["sql"],
            "baseline_match":    baseline_ex["match"],
            "baseline_success":  baseline_out["success"],
            "agent_sql":         agent_out["sql"],
            "agent_match":       agent_ex["match"],
            "agent_success":     agent_out["success"],
            "agent_attempts":    agent_out["attempts"],
            "self_corrected":    corrected,
            "error_history":     agent_out["error_history"]
        })

    # ── Compute metrics ───────────────────────────────────────────────────────
    total         = len(results)
    baseline_ex   = sum(1 for r in results if r["baseline_match"])
    agent_ex_count= sum(1 for r in results if r["agent_match"])

    # Self-correction rate: of queries that failed on attempt 1, how many recovered?
    initially_failed = [r for r in results if len(r["error_history"]) > 0]
    corrected_count  = sum(1 for r in initially_failed if r["self_corrected"])
    self_correction_rate = (
        corrected_count / len(initially_failed) * 100
        if initially_failed else 0.0
    )

    metrics = {
        "database":              db_name,
        "total_questions":       total,
        "baseline_ex":           baseline_ex,
        "baseline_ex_pct":       round(baseline_ex / total * 100, 2),
        "agent_ex":              agent_ex_count,
        "agent_ex_pct":          round(agent_ex_count / total * 100, 2),
        "initially_failed":      len(initially_failed),
        "self_corrected":        corrected_count,
        "self_correction_rate":  round(self_correction_rate, 2)
    }

    return {"metrics": metrics, "results": results}


def run_full_evaluation(db_names: list[str], limit_per_db: int = None):
    """
    Run evaluation across multiple databases and save results.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir    = RESULTS_DIR / f"eval_{timestamp}"
    run_dir.mkdir()

    all_metrics = []

    for db_name in db_names:
        semantic_path = SEMANTIC_DIR / f"{db_name}_semantic_context.json"
        if not semantic_path.exists():
            print(f"Skipping {db_name} — no semantic context found")
            continue

        db_result = evaluate_database(db_name, limit=limit_per_db)
        if not db_result:
            continue

        all_metrics.append(db_result["metrics"])

        # Save per-database results
        db_result_path = run_dir / f"{db_name}_results.json"
        with open(db_result_path, "w", encoding="utf-8") as f:
            json.dump(db_result, f, indent=2, ensure_ascii=False)

    # ── Aggregate across all databases ────────────────────────────────────────
    if all_metrics:
        total_q       = sum(m["total_questions"]  for m in all_metrics)
        total_base_ex = sum(m["baseline_ex"]      for m in all_metrics)
        total_agent_ex= sum(m["agent_ex"]         for m in all_metrics)
        total_init_fail= sum(m["initially_failed"] for m in all_metrics)
        total_corrected= sum(m["self_corrected"]   for m in all_metrics)

        aggregate = {
            "timestamp":             timestamp,
            "databases_evaluated":   len(all_metrics),
            "total_questions":       total_q,
            "baseline_ex_pct":       round(total_base_ex / total_q * 100, 2),
            "agent_ex_pct":          round(total_agent_ex / total_q * 100, 2),
            "improvement_pct":       round((total_agent_ex - total_base_ex) / total_q * 100, 2),
            "self_correction_rate":  round(total_corrected / total_init_fail * 100, 2) if total_init_fail > 0 else 0.0,
            "per_database":          all_metrics
        }

        summary_path = run_dir / "aggregate_results.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)

        print("\n" + "="*50)
        print("EVALUATION COMPLETE")
        print("="*50)
        print(f"Databases evaluated : {aggregate['databases_evaluated']}")
        print(f"Total questions     : {aggregate['total_questions']}")
        print(f"Baseline EX         : {aggregate['baseline_ex_pct']}%")
        print(f"Agent EX            : {aggregate['agent_ex_pct']}%")
        print(f"Improvement         : +{aggregate['improvement_pct']}%")
        print(f"Self-correction rate: {aggregate['self_correction_rate']}%")
        print(f"\nResults saved to: {run_dir}")


if __name__ == "__main__":
    # Start with a small pilot — 5 questions from california_schools
    run_full_evaluation(
        db_names=["california_schools"],
        limit_per_db=20
    )