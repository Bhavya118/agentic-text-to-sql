import json
import time
import sqlite3
import duckdb
from pathlib import Path
from openai import OpenAI
from config import GEMINI_API_KEY, LLM_MODEL, SEMANTIC_DIR, MAX_CORRECTIONS
from src.agent.state import AgentState

client = OpenAI(api_key=GEMINI_API_KEY)


def call_llm(prompt: str, retries: int = 5, wait: int = 30) -> str:
    """Call OpenAI with automatic retry on errors."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
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

def node_context_retrieval(state: AgentState) -> AgentState:
    """
    Matches the user's question to relevant tables and columns
    in the semantic context JSON using LLM-based relevance scoring.
    """
    db_name  = state["db_name"]
    question = state["question"]
    evidence = state.get("evidence", "")

    context_path = SEMANTIC_DIR / f"{db_name}_semantic_context.json"
    with open(context_path, "r", encoding="utf-8") as f:
        semantic_context = json.load(f)

    tables_text = []
    for table in semantic_context["tables"]:
        col_lines = []
        for col in table["columns"]:
            kpi_flag = " [KPI]" if col.get("is_kpi") else ""
            notes    = f" | note: {col['notes']}" if col.get("notes") else ""
            col_lines.append(
                f"    - {col['name']}: {col['description']}{kpi_flag}{notes}"
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
    if join_paths:
        full_context += f"\n\nKnown join paths:\n{join_paths}"

    evidence_section = f"\nAdditional hint: {evidence}\n" if evidence else ""

    prompt = f"""You are a database expert helping to identify relevant schema elements.

Question: {question}
{evidence_section}
Available schema with descriptions:
{full_context}

Return ONLY the tables and columns that are needed to answer this question.
Format your response as a concise context block that will be passed to a SQL generator.
Include table names, relevant column names, their descriptions, and any relevant join paths.
Be specific and complete — do not omit columns needed for joins or filters."""

    response_text = call_llm(prompt)
    return {**state, "retrieved_context": response_text}


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

    evidence_section = f"\nImportant hint (use exact values/formulas given here): {evidence}\n" if evidence else ""

    error_section = ""
    if error_history:
        error_section = f"""
Previous attempts failed with these errors:
{chr(10).join(f'  Attempt {i+1}: {e}' for i, e in enumerate(error_history))}

Correction instruction: {correction}

Do NOT repeat the same mistakes."""

    prompt = f"""You are an expert SQLite query writer.

Question: {question}
{evidence_section}
Relevant schema context:
{retrieved_context}
{error_section}

Rules:
- Write a single valid SQLite SQL query that answers the question.
- If a hint above gives an exact value, column condition, or formula, use it EXACTLY as written — do not paraphrase or expand abbreviations.
- Always wrap column names containing spaces or special characters in double quotes.
- Use exact column and table names from the context above — do not guess or abbreviate.
- When the question asks to "list" or "show" a particular field, exclude rows where that field itself is NULL, unless the question explicitly asks to include them.
- Evidence hints may contain pseudo-code or shorthand notation (e.g. SUBTRACT(), DIVIDE(), AVG(x WHERE y)). Translate these into valid SQLite syntax — never copy pseudo-code function names directly into SQL, as functions like SUBTRACT() and DIVIDE() do not exist in SQLite.
- When evidence gives an explicit formula (e.g. "X = A / B"), follow the exact arithmetic structure given, including order of operations and which value is the numerator vs denominator.
- When the question asks for a "rank" or "ranking", include an explicit rank/position column using ROW_NUMBER() or RANK() OVER (...), not just an ORDER BY.
- Double-check that every column referenced actually exists in the table you are selecting it from — if a column belongs to a different table in a join, reference it with the correct table alias.
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

    repeat_warning = ""
    if len(error_history) >= 2 and error_history[-1] == error_history[-2]:
        repeat_warning = "\nWARNING: The same error occurred on the previous attempt too. The previous fix did not work — propose a fundamentally different approach, not a minor tweak."

    prompt = f"""You are a SQL debugging expert.

A SQL query failed with the following error:
Error: {error_msg}
{repeat_warning}

The failing query was:
{sql}

Classify this error as one of: SYNTAX | SEMANTIC | LOGIC

If the error mentions a column not found in a table, identify which table actually contains that column (check the error message's "Candidate bindings" if present) and instruct the generator to reference it through the correct table alias or add the necessary JOIN.

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