import json
from pathlib import Path
from tqdm import tqdm
from config import DATA_DIR, SEMANTIC_DIR
from src.profiler.schema_profiler import profile_database, save_profile


def get_all_databases(dev_databases_dir: Path) -> list[Path]:
    """Return paths to all SQLite files in the dev_databases folder."""
    db_paths = []
    for db_folder in sorted(dev_databases_dir.iterdir()):
        if db_folder.is_dir():
            sqlite_files = list(db_folder.glob("*.sqlite"))
            if sqlite_files:
                db_paths.append(sqlite_files[0])
    return db_paths


def run_batch_profiler():
    dev_databases_dir = DATA_DIR / "dev_databases"
    db_paths = get_all_databases(dev_databases_dir)

    print(f"Found {len(db_paths)} databases to profile\n")

    success = []
    failed  = []

    for db_path in tqdm(db_paths, desc="Profiling databases"):
        try:
            profile = profile_database(db_path)
            save_profile(profile, SEMANTIC_DIR)
            success.append(db_path.stem)
        except Exception as e:
            failed.append((db_path.stem, str(e)))

    print(f"\n✓ Successfully profiled : {len(success)}")
    print(f"✗ Failed                : {len(failed)}")

    if failed:
        print("\nFailed databases:")
        for name, error in failed:
            print(f"  - {name}: {error}")

    # Save a summary
    summary = {"profiled": success, "failed": [f[0] for f in failed]}
    summary_path = SEMANTIC_DIR / "profiling_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    run_batch_profiler()