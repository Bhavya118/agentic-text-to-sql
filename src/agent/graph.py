from langgraph.graph import StateGraph, END
from src.agent.state import AgentState
from src.agent.nodes import (
    node_context_retrieval,
    node_sql_generator,
    node_executor,
    node_critic,
    should_continue
)


def build_agent() -> StateGraph:
    """
    Assembles the four nodes into a LangGraph stateful agent.
    
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