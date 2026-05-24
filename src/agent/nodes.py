import json
import sqlite3
import duckdb
from pathlib import Path
from google import genai
from config import GEMINI_API_KEY, LLM_MODEL, SEMANTIC_DIR, MAX_CORRECTIONS
from src.agent.state import AgentState

client = genai.Client(api_key=GEMINI_API_KEY)


# ── Node A — Context Retrieval ────────────────────────────────────────────────

def node_context_retrieval(state: AgentState) -> AgentState:
    """
    Matches the user's question to relevant tables and columns
    in the semantic context JSON using LLM-based relevance scoring.
    """
    db_name  = state["db_name"]
    question = state["question"]

    # Load semantic context from disk
    context_path = SEMANTIC_DIR / f"{db_name}_semantic_context.json"
    with open(context_path, "r", encoding="utf-8") as f:
        semantic_context = json.load(f)

    # Format the semantic context for the prompt
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

    prompt = f"""You are a database expert helping to identify relevant schema elements.

Question: {question}

Available schema with descriptions:
{full_context}

Return ONLY the tables and columns that are needed to answer this question.
Format your response as a concise context block that will be passed to a SQL generator.
Include table names, relevant column names, their descriptions, and any relevant join paths.
Be specific and complete — do not omit columns needed for joins or filters."""

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt
    )

    return {**state, "retrieved_context": response.text.strip()}


# ── Node B — SQL Generator ────────────────────────────────────────────────────

def node_sql_generator(state: AgentState) -> AgentState:
    """
    Produces a SQL query conditioned on retrieved context,
    the question, and any prior error history.
    """
    question          = state["question"]
    retrieved_context = state["retrieved_context"]
    error_history     = state.get("error_history", [])
    correction        = state.get("correction_instruction", "")

    error_section = ""
    if error_history:
        error_section = f"""
Previous attempts failed with these errors:
{chr(10).join(f'  Attempt {i+1}: {e}' for i, e in enumerate(error_history))}

Correction instruction: {correction}

Do NOT repeat the same mistakes."""

    prompt = f"""You are an expert SQL writer for SQLite databases.

Question: {question}

Relevant schema context:
{retrieved_context}
{error_section}

Write a single valid SQLite SQL query that answers the question.
Return ONLY the SQL query. No explanation, no markdown, no backticks."""

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt
    )

    sql = response.text.strip()
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

        result_str = str(result[:50])  # cap at 50 rows for state storage
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

    prompt = f"""You are a SQL debugging expert.

A SQL query failed with the following error:
Error: {error_msg}

The failing query was:
{sql}

Classify this error as one of: SYNTAX | SEMANTIC | LOGIC

Then provide a specific, actionable correction instruction in 1-2 sentences.
Tell the SQL generator exactly what to fix.

Format your response as:
ERROR_TYPE: <type>
INSTRUCTION: <what to fix>"""

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt
    )

    correction = response.text.strip()

    return {
        **state,
        "correction_instruction": correction,
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