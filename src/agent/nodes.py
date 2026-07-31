import json
import time
import sqlite3
import duckdb
from pathlib import Path
from openai import OpenAI
from config import GEMINI_API_KEY, LLM_MODEL, SEMANTIC_DIR, MAX_CORRECTIONS
from src.agent.state import AgentState
from src.common.schema_utils import (
    get_raw_schema,
    find_columns,
    extract_missing_columns,
    find_duplicate_columns,
    format_duplicate_columns
)
from src.common.value_retrieval import retrieve_matching_values, format_value_matches

client = OpenAI(api_key=GEMINI_API_KEY)


def call_llm(prompt: str, retries: int = 5, wait: int = 30) -> str:
    """Call OpenAI with automatic retry on errors."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if any(code in str(e) for code in ["429", "503", "rate_limit", "timeout"]):
                print(f"\n  API busy, waiting {wait}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait)
            else:
                raise
    raise Exception("OpenAI failed after all retries")


# ── Node A — Context Retrieval ────────────────────────────────────────────────

def _load_raw_column_lookup(db_name: str) -> dict:
    """table_name -> {column_name -> raw profiler column dict (type, PK, samples)}."""
    profile_path = SEMANTIC_DIR / f"{db_name}_raw_profile.json"
    with open(profile_path, "r", encoding="utf-8") as f:
        raw_profile = json.load(f)

    lookup = {}
    for table in raw_profile["tables"]:
        lookup[table["table_name"]] = {col["name"]: col for col in table["columns"]}
    return lookup


def _parse_selection(response_text: str) -> dict | None:
    """
    Best-effort JSON parse of Node A's schema selection. Returns None on any
    malformed output so the caller can degrade gracefully instead of crashing
    the run on a single bad LLM response.
    """
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        return None
    return data


def _render_selection(selection: dict, raw_lookup: dict, semantic_lookup: dict, join_paths_text: str) -> str:
    """
    Deterministically renders Node A's JSON selection into the schema block
    Node B sees, pulling real metadata from the raw profile / semantic context
    for ONLY the selected (table, column) pairs. Any table/column name Node A
    named that doesn't actually exist is silently dropped rather than invented —
    this is the enforcement point that keeps Node A from smuggling a
    plausible-but-wrong alternative through as if it were real.
    """
    tables_text = []
    for table_name, columns in selection.get("tables", {}).items():
        if table_name not in raw_lookup or not isinstance(columns, list):
            continue

        raw_cols = raw_lookup[table_name]
        sem_cols = semantic_lookup.get(table_name, {})

        col_lines = []
        for col_name in columns:
            if col_name not in raw_cols:
                continue
            raw_col     = raw_cols[col_name]
            sem_col     = sem_cols.get(col_name, {})
            col_type    = raw_col.get("type", "")
            pk_flag     = " [PK]" if raw_col.get("primary_key") else ""
            samples     = raw_col.get("sample_values", [])[:3]
            samples_str = f" | examples: {samples}" if samples else ""
            description = sem_col.get("description", "")
            kpi_flag    = " [KPI]" if sem_col.get("is_kpi") else ""
            notes       = f" | note: {sem_col['notes']}" if sem_col.get("notes") else ""
            col_lines.append(
                f"    - {col_name} ({col_type}){pk_flag}: {description}{kpi_flag}{samples_str}{notes}"
            )

        if col_lines:
            tables_text.append(f"  Table: {table_name}\n" + "\n".join(col_lines))

    if not tables_text:
        return "(no valid schema selection was resolved this attempt — relying on the raw schema safety net in Node B)"

    rendered = "\n\n".join(tables_text)

    join_notes = selection.get("join_notes", "")
    if isinstance(join_notes, str) and join_notes.strip():
        rendered += f"\n\nHow the selected tables connect: {join_notes.strip()}"
    if join_paths_text:
        rendered += f"\n\nKnown join paths (reference — may include tables not selected above):\n{join_paths_text}"

    return rendered


def node_context_retrieval(state: AgentState) -> AgentState:
    """
    Selects the tables/columns relevant to the question. Node A's LLM call
    returns a strict JSON enumeration of real (table, column) identifiers —
    not free prose — and Python deterministically renders the final schema
    block Node B sees. This removes the room a free-text response gives the
    model to "helpfully" describe an extra join or a plausible-but-wrong
    column as if it were the obvious pick (the failure mode found in the
    2026-07-30 ablation run — e.g. Examination.Diagnosis vs Patient.Diagnosis,
    an unnecessary double self-join on toxicology's triple-bond question).
    """
    db_name  = state["db_name"]
    question = state["question"]
    evidence = state.get("evidence", "")

    context_path = SEMANTIC_DIR / f"{db_name}_semantic_context.json"
    with open(context_path, "r", encoding="utf-8") as f:
        semantic_context = json.load(f)

    # M-Schema-style enrichment: merge in data type / PK flag / example values
    # from the raw profiler, which the synthesised semantic context doesn't carry.
    raw_lookup      = _load_raw_column_lookup(db_name)
    semantic_lookup = {
        table["table_name"]: {col["name"]: col for col in table["columns"]}
        for table in semantic_context["tables"]
    }

    tables_text = []
    for table in semantic_context["tables"]:
        raw_cols = raw_lookup.get(table["table_name"], {})
        col_lines = []
        for col in table["columns"]:
            raw_col   = raw_cols.get(col["name"], {})
            col_type  = raw_col.get("type", "")
            pk_flag   = " [PK]" if raw_col.get("primary_key") else ""
            samples   = raw_col.get("sample_values", [])[:3]
            samples_str = f" | examples: {samples}" if samples else ""
            kpi_flag  = " [KPI]" if col.get("is_kpi") else ""
            notes     = f" | note: {col['notes']}" if col.get("notes") else ""
            col_lines.append(
                f"    - {col['name']} ({col_type}){pk_flag}: {col['description']}"
                f"{kpi_flag}{samples_str}{notes}"
            )
        tables_text.append(
            f"  Table: {table['table_name']}\n"
            f"  Description: {table['description']}\n"
            + "\n".join(col_lines)
        )

    join_paths = "\n".join(
        f"  - {jp}" for jp in semantic_context.get("join_paths", [])
    )

    full_context = "\n\n".join(tables_text)

    evidence_section = f"\nAdditional hint: {evidence}\n" if evidence else ""

    value_matches  = retrieve_matching_values(db_name, question, evidence)
    value_section  = f"\n{format_value_matches(value_matches)}\n" if value_matches else ""

    duplicate_columns = find_duplicate_columns(state["db_path"])
    duplicate_section = f"\n{format_duplicate_columns(duplicate_columns)}\n" if duplicate_columns else ""

    prompt = f"""You are a database expert performing schema linking.

Question: {question}
{evidence_section}
Available schema with descriptions:
{full_context}
{value_section}
{duplicate_section}
Select the MINIMAL sufficient set of tables and columns needed to answer this question.
For every table and column you include, you must be able to point to a specific word or
phrase in the question or hint that requires it. Do not include a table, column, or join
just because it seems related or thorough — if you cannot justify it against the literal
question text, leave it out. Prefer the simplest schema path that satisfies the question
over a more elaborate one.
If a column is flagged in the schema ambiguity warning above, pick the table whose meaning
actually matches the question's intent.

Respond with ONLY a JSON object in exactly this shape, using the EXACT table and column
names from the schema above (case-sensitive) — no other text, no markdown fences:
{{
  "tables": {{
    "ExactTableName": ["ExactColumnName", "..."]
  }},
  "join_notes": "one short sentence on how the selected tables connect, or empty string if only one table"
}}"""

    response_text = call_llm(prompt)
    selection = _parse_selection(response_text)

    if selection is None:
        return {
            **state,
            "retrieved_context": "(schema selection could not be parsed this attempt — relying on the raw schema safety net in Node B)"
        }

    rendered = _render_selection(selection, raw_lookup, semantic_lookup, join_paths)
    return {**state, "retrieved_context": rendered}


# ── Condition C — Raw Schema Context (bypasses Node A) ────────────────────────

def node_raw_schema_context(state: AgentState) -> AgentState:
    """
    Ablation Condition C entry point: skips semantic context retrieval entirely
    and feeds Node B the same raw schema the baseline sees. Isolates the
    self-correction loop's contribution without any semantic context help.
    """
    raw_schema = get_raw_schema(state["db_path"])
    return {**state, "retrieved_context": raw_schema, "include_raw_fallback": False}


# ── Node B — SQL Generator ────────────────────────────────────────────────────

def node_sql_generator(state: AgentState) -> AgentState:
    """
    Produces a SQL query conditioned on retrieved context,
    the question, evidence, and any prior error history.
    """
    question          = state["question"]
    retrieved_context = state["retrieved_context"]
    evidence          = state.get("evidence", "")
    error_history     = state.get("error_history", [])
    correction        = state.get("correction_instruction", "")
    include_fallback  = state.get("include_raw_fallback", True)

    evidence_section = f"\nImportant hint (use exact values/formulas given here): {evidence}\n" if evidence else ""

    error_section = ""
    if error_history:
        error_section = f"""
Previous attempts failed with these errors:
{chr(10).join(f'  Attempt {i+1}: {e}' for i, e in enumerate(error_history))}

Correction instruction: {correction}

Do NOT repeat the same mistakes."""

    fallback_section = ""
    if include_fallback:
        raw_schema = get_raw_schema(state["db_path"])
        fallback_section = f"""
Full raw database schema (safety net — use this if a table or column you need is missing from the context above; it may have been dropped during summarisation):
{raw_schema}
"""

        value_matches = retrieve_matching_values(state["db_name"], question, evidence)
        value_matches_str = format_value_matches(value_matches)
        if value_matches_str:
            fallback_section += f"\n{value_matches_str}\n"

        duplicate_columns = find_duplicate_columns(state["db_path"])
        duplicate_columns_str = format_duplicate_columns(duplicate_columns)
        if duplicate_columns_str:
            fallback_section += f"\n{duplicate_columns_str}\n"

    prompt = f"""You are an expert SQLite query writer.

Question: {question}
{evidence_section}
Relevant schema context:
{retrieved_context}
{fallback_section}
{error_section}

Rules:
- Write a single valid SQLite SQL query that answers the question.
- If a hint above gives an exact value, column condition, or formula, use it EXACTLY as written — do not paraphrase or expand abbreviations.
- Always wrap column names containing spaces or special characters in double quotes.
- Use exact column and table names from the context above — do not guess or abbreviate.
- When the question asks to "list" or "show" a particular field, exclude rows where that field itself is NULL, unless the question explicitly asks to include them.
- Evidence hints may contain pseudo-code or shorthand notation (e.g. SUBTRACT(), DIVIDE(), AVG(x WHERE y)). Translate these into valid SQLite syntax — never copy pseudo-code function names directly into SQL, as functions like SUBTRACT() and DIVIDE() do not exist in SQLite.
- When evidence gives an explicit formula (e.g. "X = A / B"), follow the exact arithmetic structure given, including order of operations and which value is the numerator vs denominator.
- When the question asks for a "rank" or "ranking", include an explicit rank/position column using RANK() OVER (...), not just an ORDER BY. Prefer RANK() over ROW_NUMBER() — RANK() gives tied values the same rank, which is almost always the intended meaning; only use ROW_NUMBER() if the question explicitly needs a unique sequential position even among ties.
- Double-check that every column referenced actually exists in the table you are selecting it from — if a column belongs to a different table in a join, reference it with the correct table alias.
- If a schema ambiguity warning above flags a column name that exists on multiple tables, pick the table whose meaning actually matches the question's intent — do not default to whichever table appeared first.
- Order the columns in your SELECT clause to match the order the corresponding entities are mentioned or requested in the question — do not reorder them for readability, since column order is part of exact-match grading.
- Do not add a JOIN, table, or extra condition that isn't strictly required to answer the question — prefer the simplest query that satisfies the literal question over a more elaborate one, even if the elaborate one seems more thorough.
- Return ONLY the SQL query. No explanation, no markdown, no backticks."""

    response_text = call_llm(prompt)

    sql = response_text
    if sql.startswith("```"):
        sql = sql.split("```")[1]
        if sql.startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()

    return {**state, "generated_sql": sql}


# ── Node C — Executor ─────────────────────────────────────────────────────────

def node_executor(state: AgentState) -> AgentState:
    """
    Executes the generated SQL against DuckDB.
    On success: stores result. On failure: logs error to state.
    """
    sql     = state["generated_sql"]
    db_path = state["db_path"]

    try:
        conn   = duckdb.connect(db_path)
        result = conn.execute(sql).fetchall()
        conn.close()

        result_str = str(result[:50])
        return {
            **state,
            "execution_result":  result_str,
            "execution_error":   None,
            "execution_success": True
        }

    except Exception as e:
        error_history = state.get("error_history", [])
        error_msg     = str(e)
        return {
            **state,
            "execution_result":  None,
            "execution_error":   error_msg,
            "execution_success": False,
            "error_history":     error_history + [error_msg]
        }


# ── Node D — Critic ───────────────────────────────────────────────────────────

def node_critic(state: AgentState) -> AgentState:
    """
    Analyses the execution error, classifies it, and formulates
    a targeted correction instruction for Node B.
    """
    sql           = state["generated_sql"]
    error_msg     = state["execution_error"]
    error_history = state.get("error_history", [])
    db_path       = state["db_path"]

    repeat_warning = ""
    if len(error_history) >= 2 and error_history[-1] == error_history[-2]:
        repeat_warning = "\nWARNING: The same error occurred on the previous attempt too. The previous fix did not work — propose a fundamentally different approach, not a minor tweak."

    # Deterministic schema check — resolves "column not found" errors against the
    # real schema in plain Python (no LLM call), so the critic gets ground truth
    # instead of having to parse/guess it from the raw error message.
    schema_hint = ""
    hint_lines = []
    for missing_col in extract_missing_columns(error_msg):
        owners = find_columns(db_path, missing_col)
        if owners:
            hint_lines.append(
                f"  - Column '{missing_col}' is not on the table you referenced it from. "
                f"It actually exists on: {', '.join(owners)}."
            )
    if hint_lines:
        schema_hint = "\nDeterministic schema check (ground truth — trust this over guessing):\n" + "\n".join(hint_lines)

    prompt = f"""You are a SQL debugging expert.

A SQL query failed with the following error:
Error: {error_msg}
{repeat_warning}
{schema_hint}

The failing query was:
{sql}

Classify this error as one of: SYNTAX | SEMANTIC | LOGIC

If the error mentions a column not found in a table, identify which table actually contains that column (check the error message's "Candidate bindings" if present, and the deterministic schema check above if given) and instruct the generator to reference it through the correct table alias or add the necessary JOIN.

Then provide a specific, actionable correction instruction in 1-2 sentences.

Format your response as:
ERROR_TYPE: <type>
INSTRUCTION: <what to fix>"""

    response_text = call_llm(prompt)

    return {
        **state,
        "correction_instruction": response_text,
        "attempt_number": state.get("attempt_number", 1) + 1
    }


# ── Routing function ──────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    """
    Decides whether to continue correcting or stop.
    Returns 'correct' to route back to Node B, or 'end' to finish.
    """
    if state["execution_success"]:
        return "end"
    if state.get("attempt_number", 1) >= MAX_CORRECTIONS:
        return "end"
    return "correct"