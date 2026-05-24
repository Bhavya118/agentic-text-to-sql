from typing import TypedDict, Optional


class AgentState(TypedDict):
    """
    Shared state object passed between all nodes in the LangGraph agent.
    Each node reads from and writes to this state.
    """
    # Input
    question:        str           # The user's natural language question
    db_name:         str           # Which database to query
    db_path:         str           # Full path to the SQLite file

    # Context retrieval (Node A output)
    retrieved_context: str         # Relevant tables/columns from semantic context

    # SQL generation (Node B output)
    generated_sql:   str           # The current SQL query attempt

    # Execution (Node C output)
    execution_result: Optional[str]  # Result table as string, if successful
    execution_error:  Optional[str]  # Error message, if failed
    execution_success: bool          # True if last execution succeeded

    # Correction loop (Node D output)
    error_history:   list[str]     # All errors seen so far
    correction_instruction: Optional[str]  # Targeted fix from critic
    attempt_number:  int           # Current attempt (1, 2, 3)