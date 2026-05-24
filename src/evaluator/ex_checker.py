import sqlite3
import duckdb
from pathlib import Path


def execute_sql(sql: str, db_path: Path) -> tuple[list, str | None]:
    """
    Execute a SQL query against a database.
    Returns (results, error_message).
    """
    try:
        conn   = duckdb.connect(str(db_path))
        result = conn.execute(sql).fetchall()
        conn.close()
        return result, None
    except Exception as e:
        return [], str(e)


def normalise_result(result: list) -> set:
    """
    Normalise a result table for comparison.
    Converts to a set of tuples with lowercased strings.
    Order-independent comparison.
    """
    normalised = set()
    for row in result:
        normalised_row = tuple(
            str(v).strip().lower() if v is not None else "none"
            for v in row
        )
        normalised.add(normalised_row)
    return normalised


def check_execution_accuracy(
    predicted_sql: str,
    gold_sql:      str,
    db_path:       Path
) -> dict:
    """
    Compare predicted SQL result against gold SQL result.
    Returns a dict with match status and details.
    """
    pred_result, pred_error = execute_sql(predicted_sql, db_path)
    gold_result, gold_error = execute_sql(gold_sql,      db_path)

    if gold_error:
        return {
            "match":       False,
            "pred_result": pred_result,
            "gold_result": gold_result,
            "pred_error":  pred_error,
            "gold_error":  gold_error,
            "note":        "Gold SQL failed — skip this question"
        }

    if pred_error:
        return {
            "match":       False,
            "pred_result": [],
            "gold_result": gold_result,
            "pred_error":  pred_error,
            "gold_error":  None,
            "note":        "Predicted SQL failed to execute"
        }

    pred_norm = normalise_result(pred_result)
    gold_norm = normalise_result(gold_result)

    match = (pred_norm == gold_norm)

    return {
        "match":       match,
        "pred_result": pred_result[:10],
        "gold_result": gold_result[:10],
        "pred_error":  None,
        "gold_error":  None,
        "note":        "exact match" if match else "result mismatch"
    }


if __name__ == "__main__":
    from config import DATA_DIR

    db_path = DATA_DIR / "dev_databases" / "california_schools" / "california_schools.sqlite"

    # Test 1: matching queries
    pred_sql = "SELECT MAX(AvgScrMath) FROM satscores"
    gold_sql = "SELECT MAX(AvgScrMath) FROM satscores WHERE rtype = 'S'"

    print("Test 1 — potentially mismatched queries:")
    result = check_execution_accuracy(pred_sql, gold_sql, db_path)
    print(f"  Match      : {result['match']}")
    print(f"  Pred result: {result['pred_result']}")
    print(f"  Gold result: {result['gold_result']}")
    print(f"  Note       : {result['note']}")

    # Test 2: identical queries
    print("\nTest 2 — identical queries:")
    result2 = check_execution_accuracy(gold_sql, gold_sql, db_path)
    print(f"  Match      : {result2['match']}")
    print(f"  Note       : {result2['note']}")