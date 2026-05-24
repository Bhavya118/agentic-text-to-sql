import json
import time
from tqdm import tqdm
from config import SEMANTIC_DIR
from src.synthesiser.llm_synthesiser import synthesise_semantic_context, save_semantic_context


def get_all_db_names() -> list[str]:
    """Get all database names that have a raw profile."""
    profiles = list(SEMANTIC_DIR.glob("*_raw_profile.json"))
    return [p.stem.replace("_raw_profile", "") for p in sorted(profiles)]


def run_batch_synthesiser():
    db_names = get_all_db_names()
    print(f"Found {len(db_names)} databases to synthesise\n")

    success = []
    failed  = []

    for db_name in tqdm(db_names, desc="Synthesising semantic context"):
        try:
            semantic_context = synthesise_semantic_context(db_name)
            save_semantic_context(semantic_context, SEMANTIC_DIR)
            success.append(db_name)
            # Small delay to respect API rate limits
            time.sleep(2)
        except Exception as e:
            failed.append((db_name, str(e)))
            print(f"\n  ✗ Failed: {db_name} — {e}")

    print(f"\n✓ Successfully synthesised : {len(success)}")
    print(f"✗ Failed                   : {len(failed)}")

    if failed:
        print("\nFailed databases:")
        for name, error in failed:
            print(f"  - {name}: {error}")

    summary_path = SEMANTIC_DIR / "synthesis_summary.json"
    with open(summary_path, "w") as f:
        json.dump({"synthesised": success, "failed": [f[0] for f in failed]}, f, indent=2)
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    run_batch_synthesiser()