# Agentic AI Architecture for Industrial Text-to-SQL

**MSc Mechatronics Thesis** | Ravensburg-Weingarten University of Applied Sciences  
**Author:** Bhavya Upadhyay  
**Supervisor:** Prof. Dr.-Ing. Wolfram Höpken  
**Co-Supervisor:** Prof. Dr. rer. nat. Marius Hofmeister

---

## Research Question

> To what extent does automated semantic context generation combined with a self-correcting agentic execution loop improve SQL generation accuracy compared to one-shot LLM prompting on complex industrial-style database schemas?

---

## System Architecture

```mermaid
flowchart TD
    A[BIRD SQLite Database] --> B[Component 1: Semantic Context Generator]
    
    subgraph B[Component 1: Semantic Context Generator]
        B1[Schema Profiler\nPRAGMA extraction\ntable names, columns, PKs, FKs\nsample values, distributions] --> B2[LLM Synthesiser\nGPT generates\nnatural language descriptions\nKPI flags, join paths]
        B2 --> B3[semantic_context.json\nPermanent reusable document\nper database]
    end

    B3 --> C[Component 2: LangGraph Agent]
    A --> C

    subgraph C[Component 2: LangGraph Agent]
        C1[Node A: Context Retrieval\nMatches question to relevant\ntables and columns] --> C2[Node B: SQL Generator\nGenerates SQL from context\nquestion and error history]
        C2 --> C3[Node C: Executor\nRuns SQL against DuckDB]
        C3 -->|Success| C5[Return Result]
        C3 -->|Failure| C4[Node D: Critic\nClassifies error\nSYNTAX / SEMANTIC / LOGIC\nFormulates targeted fix]
        C4 -->|Retry max 3x| C2
    end

    subgraph D[Component 3: Evaluation Framework]
        D1[Baseline\nOne-shot GPT\nRaw schema only\nNo correction] 
        D2[Agent\nSemantic context\nSelf-correction loop]
        D3[EX Checker\nCompares result tables\nagainst gold SQL]
        D4[McNemar Test\nStatistical significance]
    end

    C --> D2
    A --> D1
    D1 --> D3
    D2 --> D3
    D3 --> D4
```

---

## Results — Full BIRD Dev Set (1,534 questions, GPT-4o)

| Metric | Value |
|--------|-------|
| Baseline EX (one-shot, raw schema) | 28.23% |
| Agent EX (semantic context + self-correction) | 38.14% |
| Improvement | +9.91 pp |
| Self-correction rate | 68.6% |
| Agent execution failures | 5.0% vs 15.1% baseline |

---

## Key Findings

- **Evidence routing matters in multi-step pipelines** — evidence hints injected only into Node A's summarization step are silently paraphrased and lose precision; passing them verbatim directly to the SQL generation node is required
- **Benchmark annotation conventions vs real SQL correctness** — some accuracy losses reflect BIRD's unstated gold-query conventions (e.g. implicit NULL exclusion) rather than genuine reasoning failures
- **Data integrity issue discovered in BIRD** — 48 of 129 questions (37.2%) in `european_football_2` reference columns that do not exist in the distributed SQLite file; gold SQL itself fails to execute on this database

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Agentic framework | LangGraph |
| Database engine | DuckDB + SQLite |
| LLM | GPT-4o via OpenAI API |
| Benchmark | BIRD (Li et al., 2023) |

---

## Project Structure

```
thesis_project/
├── data/bird/                    # BIRD benchmark databases
├── src/
│   ├── profiler/                 # Component 1 — schema profiling
│   ├── synthesiser/              # Component 1 — LLM synthesis
│   ├── agent/                    # Component 2 — LangGraph nodes
│   └── evaluator/                # Component 3 — evaluation harness
├── outputs/
│   ├── semantic_context/         # Generated JSON files per database
│   └── results/                  # Evaluation results and logs
└── config.py                     # API keys, paths, hyperparameters
```

---

## Benchmark

BIRD: A BIg Bench for Large-Scale Database Grounded Text-to-SQLs  
Li et al., NeurIPS 2023 — [https://bird-bench.github.io/](https://bird-bench.github.io/)