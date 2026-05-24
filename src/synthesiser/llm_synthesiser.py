import json
from pathlib import Path
from google import genai
from config import GEMINI_API_KEY, LLM_MODEL, SEMANTIC_DIR

client = genai.Client(api_key=GEMINI_API_KEY)


def load_raw_profile(db_name: str) -> dict:
    """Load the raw profile JSON for a given database."""
    profile_path = SEMANTIC_DIR / f"{db_name}_raw_profile.json"
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_synthesis_prompt(profile: dict) -> str:
    """
    Build the prompt sent to the LLM.
    We pass the raw profile and ask for business-friendly descriptions.
    """
    db_name = profile["database_name"]
    tables_summary = []

    for table in profile["tables"]:
        col_lines = []
        for col in table["columns"]:
            samples = col["sample_values"][:3]
            col_lines.append(
                f"  - {col['name']} ({col['type']}) | samples: {samples}"
            )
        tables_summary.append(
            f"Table: {table['table_name']} ({table['row_count']} rows)\n"
            + "\n".join(col_lines)
        )

    tables_text = "\n\n".join(tables_summary)

    prompt = f"""You are a database documentation expert. 
You are given the raw schema of a database named '{db_name}'.
Your task is to generate a structured semantic context document in JSON format.

For each table, provide:
- "description": a 1-2 sentence plain English description of what the table contains
- "columns": for each column provide:
  - "description": plain English explanation of what the column means
  - "is_kpi": true if this column is a business metric or KPI (counts, amounts, rates, scores), false otherwise
  - "notes": any important notes about values, codes, or abbreviations (empty string if none)

Also provide at the end:
- "join_paths": a list of natural join relationships between tables, each as a plain English sentence

Here is the raw schema:

{tables_text}

Respond ONLY with a valid JSON object. No markdown, no backticks, no explanation.
Use this exact structure:
{{
  "database_name": "{db_name}",
  "tables": [
    {{
      "table_name": "example_table",
      "description": "...",
      "columns": [
        {{
          "name": "column_name",
          "description": "...",
          "is_kpi": false,
          "notes": ""
        }}
      ]
    }}
  ],
  "join_paths": [
    "Table A joins to Table B on column X"
  ]
}}"""
    return prompt


def synthesise_semantic_context(db_name: str) -> dict:
    """
    Load raw profile, send to LLM, parse and return semantic context.
    """
    profile = load_raw_profile(db_name)
    prompt  = build_synthesis_prompt(profile)

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt
    )

    raw_text = response.text.strip()

    # Strip markdown fences if model adds them despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    semantic_context = json.loads(raw_text)
    return semantic_context


def save_semantic_context(semantic_context: dict, output_dir: Path) -> Path:
    """Save the semantic context JSON to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    db_name     = semantic_context["database_name"]
    output_path = output_dir / f"{db_name}_semantic_context.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(semantic_context, f, indent=2, ensure_ascii=False)
    return output_path


if __name__ == "__main__":
    # Test on california_schools first
    db_name = "california_schools"
    print(f"Synthesising semantic context for: {db_name}")

    semantic_context = synthesise_semantic_context(db_name)

    print(f"\nTables described: {len(semantic_context['tables'])}")
    for t in semantic_context["tables"]:
        print(f"\n  Table: {t['table_name']}")
        print(f"  Description: {t['description']}")
        kpi_cols = [c['name'] for c in t['columns'] if c.get('is_kpi')]
        print(f"  KPI columns: {kpi_cols}")

    print(f"\nJoin paths:")
    for jp in semantic_context.get("join_paths", []):
        print(f"  - {jp}")

    output_path = save_semantic_context(semantic_context, SEMANTIC_DIR)
    print(f"\nSemantic context saved to: {output_path}")