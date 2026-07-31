from langgraph.graph import StateGraph, END
from src.agent.state import AgentState
from src.agent.nodes import (
    node_context_retrieval,
    node_sql_generator,
    node_executor,
    node_critic,
    node_raw_schema_context,
    should_continue
)


def build_agent() -> StateGraph:
    """
    Ablation Condition D — the full agent. Assembles all four nodes.

    Flow:
    A (Context Retrieval)
        → B (SQL Generator)
            → C (Executor)
                → [success] END
                → [failure] D (Critic)
                    → B (retry, up to MAX_CORRECTIONS times)
    """
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("context_retrieval", node_context_retrieval)
    graph.add_node("sql_generator",     node_sql_generator)
    graph.add_node("executor",          node_executor)
    graph.add_node("critic",            node_critic)

    # Define edges
    graph.set_entry_point("context_retrieval")
    graph.add_edge("context_retrieval", "sql_generator")
    graph.add_edge("sql_generator",     "executor")

    # Conditional edge after executor
    graph.add_conditional_edges(
        "executor",
        should_continue,
        {
            "end":     END,
            "correct": "critic"
        }
    )

    # Critic always routes back to SQL generator
    graph.add_edge("critic", "sql_generator")

    return graph.compile()


def build_condition_b_context_only() -> StateGraph:
    """
    Ablation Condition B — semantic context, no self-correction.

    Isolates Node A's contribution: same context retrieval as the full agent,
    but the executor always ends the run (no critic, no retry) even on failure.

    Flow: A (Context Retrieval) → B (SQL Generator) → C (Executor) → END
    """
    graph = StateGraph(AgentState)

    graph.add_node("context_retrieval", node_context_retrieval)
    graph.add_node("sql_generator",     node_sql_generator)
    graph.add_node("executor",          node_executor)

    graph.set_entry_point("context_retrieval")
    graph.add_edge("context_retrieval", "sql_generator")
    graph.add_edge("sql_generator",     "executor")
    graph.add_edge("executor", END)

    return graph.compile()


def build_condition_c_correction_only() -> StateGraph:
    """
    Ablation Condition C — self-correction, no semantic context.

    Isolates Node D's contribution: Node A is replaced with a raw-schema
    loader (same schema the baseline sees, no LLM summarisation), then the
    normal correction loop runs on top of it.

    Flow:
    Raw Schema Loader
        → B (SQL Generator)
            → C (Executor)
                → [success] END
                → [failure] D (Critic)
                    → B (retry, up to MAX_CORRECTIONS times)
    """
    graph = StateGraph(AgentState)

    graph.add_node("raw_schema_context", node_raw_schema_context)
    graph.add_node("sql_generator",      node_sql_generator)
    graph.add_node("executor",           node_executor)
    graph.add_node("critic",             node_critic)

    graph.set_entry_point("raw_schema_context")
    graph.add_edge("raw_schema_context", "sql_generator")
    graph.add_edge("sql_generator",      "executor")

    graph.add_conditional_edges(
        "executor",
        should_continue,
        {
            "end":     END,
            "correct": "critic"
        }
    )

    graph.add_edge("critic", "sql_generator")

    return graph.compile()


if __name__ == "__main__":
    from config import DATA_DIR

    agent = build_agent()

    # Test on california_schools
    db_path = str(DATA_DIR / "dev_databases" / "california_schools" / "california_schools.sqlite")

    initial_state = {
        "question":              "What is the highest average SAT math score among all schools?",
        "db_name":               "california_schools",
        "db_path":               db_path,
        "retrieved_context":     "",
        "generated_sql":         "",
        "execution_result":      None,
        "execution_error":       None,
        "execution_success":     False,
        "error_history":         [],
        "correction_instruction": None,
        "attempt_number":        1
    }

    print("Running agent...\n")
    final_state = agent.invoke(initial_state)

    print(f"Question  : {final_state['question']}")
    print(f"SQL       : {final_state['generated_sql']}")
    print(f"Success   : {final_state['execution_success']}")
    print(f"Result    : {final_state['execution_result']}")
    print(f"Attempts  : {final_state['attempt_number']}")
    if final_state.get('error_history'):
        print(f"Errors    : {final_state['error_history']}")