import json
import random
from config import DATA_DIR, SEMANTIC_DIR


def create_stratified_sample(n_per_db: int = 5, seed: int = 42) -> list[dict]:
    """
    Create a fixed, reproducible sample of questions across all databases.
    Same seed = same questions every time, for fair comparison between versions.
    """
    with open(DATA_DIR / "dev.json", "r", encoding="utf-8") as f:
        all_questions = json.load(f)

    db_names = [
        p.stem.replace("_semantic_context", "")
        for p in sorted(SEMANTIC_DIR.glob("*_semantic_context.json"))
    ]

    random.seed(seed)
    sample = []

    for db_name in db_names:
        db_questions = [q for q in all_questions if q["db_id"] == db_name]
        n = min(n_per_db, len(db_questions))
        sample.extend(random.sample(db_questions, n))

    return sample


def save_sample(sample: list[dict], path: str = "dev_sample_50.json"):
    """Save the sample so it's identical across all test runs."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(sample)} questions to {path}")


if __name__ == "__main__":
    sample = create_stratified_sample(n_per_db=5, seed=42)
    save_sample(sample, "data/bird/dev_sample_50.json")

    print(f"\nTotal questions: {len(sample)}")
    db_counts = {}
    for q in sample:
        db_counts[q["db_id"]] = db_counts.get(q["db_id"], 0) + 1
    for db, count in sorted(db_counts.items()):
        print(f"  {db}: {count}")