import json
import time
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
from config import DATA_DIR, RESULTS_DIR, SEMANTIC_DIR
from src.evaluator.baseline import run_baseline
from src.evaluator.ex_checker import check_execution_accuracy
from src.agent.graph import (
    build_agent,
    build_condition_b_context_only,
    build_condition_c_correction_only
)

# Ablation conditions beyond the baseline (Condition A).
# Keys double as the field name each condition's per-question result is stored under.
CONDITION_BUILDERS = {
    "context_only":    build_condition_b_context_only,   # Condition B
    "correction_only": build_condition_c_correction_only,  # Condition C
    "full_agent":      build_agent,                        # Condition D
}


def load_bird_questions(db_name: str, limit: int = None, use_sample: bool = False) -> list[dict]:
    """Load questions from BIRD dev.json for a specific database.

    If use_sample=True, loads from the fixed 50-question sample instead,
    ensuring consistent questions across experiment runs.
    """
    if use_sample:
        source_path = DATA_DIR / "dev_sample_50.json"
    else:
        source_path = DATA_DIR / "dev.json"

    with open(source_path, "r", encoding="utf-8") as f:
        all_questions = json.load(f)

    db_questions = [q for q in all_questions if q["db_id"] == db_name]

    if limit:
        db_questions = db_questions[:limit]

    return db_questions


def run_agent_on_question(agent, question: str, db_name: str, db_path: Path, evidence: str = "") -> dict:
    """Run one ablation condition's compiled graph on a single question."""
    initial_state = {
        "question":               question,
        "db_name":                db_name,
        "db_path":                str(db_path),
        "evidence":               evidence,
        "retrieved_context":      "",
        "include_raw_fallback":   True,
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
        "sql":           final_state["generated_sql"],
        "success":       final_state["execution_success"],
        "attempts":      final_state["attempt_number"],
        "error_history": final_state.get("error_history", []),
        "result":        final_state.get("execution_result")
    }


def load_checkpoint(checkpoint_path: Path) -> dict:
    """Load existing checkpoint if it exists."""
    if checkpoint_path.exists():
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_ids": [], "results": []}


def save_checkpoint(checkpoint_path: Path, checkpoint: dict):
    """Save checkpoint to disk after each question."""
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def evaluate_database(db_name: str, run_dir: Path, limit: int = None, use_sample: bool = False) -> dict:
    """
    Run baseline and agent on all questions for one database.
    Supports checkpoint/resume — skips already completed questions.
    """
    db_path   = DATA_DIR / "dev_databases" / db_name / f"{db_name}.sqlite"
    questions = load_bird_questions(db_name, limit, use_sample)

    if not questions:
        print(f"  No questions found for {db_name}")
        return {}

    # ── Load checkpoint ───────────────────────────────────────────────────────
    checkpoint_path = run_dir / f"{db_name}_checkpoint.json"
    checkpoint      = load_checkpoint(checkpoint_path)
    completed_ids   = set(checkpoint["completed_ids"])
    results         = checkpoint["results"]

    remaining = [q for q in questions if str(q.get("question_id", q.get("id", ""))) not in completed_ids]

    print(f"\n  {db_name}: {len(questions)} total, {len(completed_ids)} already done, {len(remaining)} remaining")

    if not remaining:
        print(f"  All questions already completed for {db_name}")
        return compute_metrics(db_name, results)

    # Build all three agent-variant graphs once, reused across every question.
    agents = {key: builder() for key, builder in CONDITION_BUILDERS.items()}

    for q in tqdm(remaining, desc=f"  Evaluating {db_name}"):
        question = q["question"]
        gold_sql = q["SQL"]
        evidence = q.get("evidence", "")
        q_id     = str(q.get("question_id", q.get("id", "unknown")))

        # ── Condition A — Baseline ──────────────────────────────────────────────
        try:
            baseline_out = run_baseline(question, db_path, evidence)
            baseline_ex  = check_execution_accuracy(
                baseline_out["sql"], gold_sql, db_path
            ) if baseline_out["success"] else {"match": False, "note": "execution failed"}
        except Exception as e:
            baseline_out = {"sql": "", "success": False, "error": str(e)}
            baseline_ex  = {"match": False, "note": f"error: {e}"}

        time.sleep(3)

        result = {
            "question_id": q_id,
            "question":    question,
            "gold_sql":    gold_sql,
            "evidence":    evidence,
            "baseline": {
                "sql":     baseline_out["sql"],
                "match":   baseline_ex["match"],
                "success": baseline_out["success"]
            }
        }

        # ── Conditions B, C, D — agent variants ──────────────────────────────────
        for cond_key, agent in agents.items():
            try:
                agent_out = run_agent_on_question(agent, question, db_name, db_path, evidence)
                agent_ex  = check_execution_accuracy(
                    agent_out["sql"], gold_sql, db_path
                ) if agent_out["success"] else {"match": False, "note": "execution failed"}
            except Exception as e:
                agent_out = {"sql": "", "success": False, "attempts": 1, "error_history": [], "result": None}
                agent_ex  = {"match": False, "note": f"error: {e}"}

            time.sleep(3)

            corrected = (agent_out["attempts"] > 1 and agent_out["success"])

            result[cond_key] = {
                "sql":            agent_out["sql"],
                "match":          agent_ex["match"],
                "success":        agent_out["success"],
                "attempts":       agent_out["attempts"],
                "self_corrected": corrected,
                "error_history":  agent_out["error_history"]
            }

        results.append(result)

        # ── Save checkpoint after every question ──────────────────────────────
        completed_ids.add(q_id)
        checkpoint = {"completed_ids": list(completed_ids), "results": results}
        save_checkpoint(checkpoint_path, checkpoint)

    return compute_metrics(db_name, results)


def compute_metrics(db_name: str, results: list) -> dict:
    """Compute per-condition EX and self-correction metrics from results."""
    total       = len(results)
    baseline_ex = sum(1 for r in results if r["baseline"]["match"])

    metrics = {
        "database":        db_name,
        "total_questions": total,
        "baseline_ex":     baseline_ex,
        "baseline_ex_pct": round(baseline_ex / total * 100, 2) if total else 0.0,
    }

    for cond_key in CONDITION_BUILDERS:
        cond_ex = sum(1 for r in results if r[cond_key]["match"])

        initially_failed = [r for r in results if len(r[cond_key]["error_history"]) > 0]
        corrected_count  = sum(1 for r in initially_failed if r[cond_key]["self_corrected"])
        self_correction_rate = (
            corrected_count / len(initially_failed) * 100
            if initially_failed else 0.0
        )

        metrics[f"{cond_key}_ex"]                    = cond_ex
        metrics[f"{cond_key}_ex_pct"]                 = round(cond_ex / total * 100, 2) if total else 0.0
        metrics[f"{cond_key}_initially_failed"]       = len(initially_failed)
        metrics[f"{cond_key}_self_corrected"]         = corrected_count
        metrics[f"{cond_key}_self_correction_rate"]   = round(self_correction_rate, 2)

    return {"metrics": metrics, "results": results}


def run_full_evaluation(db_names: list[str], limit_per_db: int = None, run_id: str = None, use_sample: bool = False):
    """
    Run evaluation across multiple databases with checkpoint/resume support.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Use existing run_id or create new one ─────────────────────────────────
    if run_id:
        run_dir = RESULTS_DIR / run_id
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir   = RESULTS_DIR / f"eval_{timestamp}"

    run_dir.mkdir(exist_ok=True)
    print(f"Run directory: {run_dir}")

    all_metrics = []

    for db_name in db_names:
        semantic_path = SEMANTIC_DIR / f"{db_name}_semantic_context.json"
        if not semantic_path.exists():
            print(f"Skipping {db_name} — no semantic context found")
            continue

        db_result = evaluate_database(db_name, run_dir, limit=limit_per_db, use_sample=use_sample)
        if not db_result:
            continue

        all_metrics.append(db_result["metrics"])

        # Save per-database results
        db_result_path = run_dir / f"{db_name}_results.json"
        with open(db_result_path, "w", encoding="utf-8") as f:
            json.dump(db_result, f, indent=2, ensure_ascii=False)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    if all_metrics:
        total_q       = sum(m["total_questions"] for m in all_metrics)
        total_base_ex = sum(m["baseline_ex"]      for m in all_metrics)

        aggregate = {
            "run_id":              run_dir.name,
            "databases_evaluated": len(all_metrics),
            "total_questions":     total_q,
            "baseline_ex_pct":     round(total_base_ex / total_q * 100, 2),
        }

        for cond_key in CONDITION_BUILDERS:
            cond_ex_total   = sum(m[f"{cond_key}_ex"]                  for m in all_metrics)
            init_fail_total = sum(m[f"{cond_key}_initially_failed"]     for m in all_metrics)
            corrected_total = sum(m[f"{cond_key}_self_corrected"]       for m in all_metrics)

            aggregate[f"{cond_key}_ex_pct"] = round(cond_ex_total / total_q * 100, 2)
            aggregate[f"{cond_key}_improvement_pct"] = round(
                (cond_ex_total - total_base_ex) / total_q * 100, 2
            )
            aggregate[f"{cond_key}_self_correction_rate"] = (
                round(corrected_total / init_fail_total * 100, 2) if init_fail_total > 0 else 0.0
            )

        aggregate["per_database"] = all_metrics

        summary_path = run_dir / "aggregate_results.json"
        with open(summary_path, "w") as f:
            json.dump(aggregate, f, indent=2)

        print("\n" + "="*50)
        print("EVALUATION COMPLETE — 4-CONDITION ABLATION")
        print("="*50)
        print(f"Run ID              : {aggregate['run_id']}")
        print(f"Databases evaluated : {aggregate['databases_evaluated']}")
        print(f"Total questions     : {aggregate['total_questions']}")
        print(f"Condition A — baseline           : {aggregate['baseline_ex_pct']}%")
        print(f"Condition B — context only       : {aggregate['context_only_ex_pct']}%  "
              f"(Δ {aggregate['context_only_improvement_pct']:+.2f} pp)")
        print(f"Condition C — correction only    : {aggregate['correction_only_ex_pct']}%  "
              f"(Δ {aggregate['correction_only_improvement_pct']:+.2f} pp, "
              f"self-correction {aggregate['correction_only_self_correction_rate']}%)")
        print(f"Condition D — full agent         : {aggregate['full_agent_ex_pct']}%  "
              f"(Δ {aggregate['full_agent_improvement_pct']:+.2f} pp, "
              f"self-correction {aggregate['full_agent_self_correction_rate']}%)")
        print(f"\nResults saved to: {run_dir}")


if __name__ == "__main__":
    from config import SEMANTIC_DIR
    db_names = [
        p.stem.replace("_semantic_context", "")
        for p in sorted(SEMANTIC_DIR.glob("*_semantic_context.json"))
    ]

    print(f"Databases to evaluate: {db_names}")

    # Full BIRD dev set (1,534 questions) -- final thesis evaluation run.
    run_full_evaluation(
        db_names=db_names,
        limit_per_db=None,
        use_sample=False
    )