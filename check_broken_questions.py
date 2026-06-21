import json
from config import DATA_DIR

with open(DATA_DIR / "dev.json") as f:
    questions = json.load(f)

ef_questions = [q for q in questions if q["db_id"] == "european_football_2"]
broken = [q for q in ef_questions if "player_name" in q["SQL"] and "Player_old" not in q["SQL"] and "FROM Player " in q["SQL"].replace("Player_Attributes","").replace("Player_old","")]

print(f"Total european_football_2 questions: {len(ef_questions)}")
print(f"Potentially broken (player_name on wrong table): {len(broken)}")
for q in broken[:5]:
    print(q["question"])
    print(q["SQL"])
    print()