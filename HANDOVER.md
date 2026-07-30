# Claude Code Context — MSc Thesis Project

## Identity
- **Author:** Bhavya Upadhyay
- **Programme:** MSc Mechatronics
- **University:** Ravensburg-Weingarten University of Applied Sciences
- **Supervisor:** Prof. Dr.-Ing. Wolfram Höpken
- **Co-Supervisor:** Prof. Dr. rer. nat. Marius Hofmeister
- **Timeline:** 6 months total. Currently Month 3.

---

## Thesis Title
Agentic AI Architecture for Industrial Text-to-SQL: Automated Semantic Context Generation and Self-Correcting Loop

## Research Question
To what extent does automated semantic context generation combined with a self-correcting agentic execution loop improve SQL generation accuracy compared to one-shot LLM prompting on complex industrial-style database schemas?

---

## Technology Stack
- **Language:** Python 3.12
- **Agentic framework:** LangGraph
- **Database engine:** DuckDB (evaluation) + SQLite/sqlite3 (profiling)
- **LLM:** GPT-4o via OpenAI API
- **Benchmark:** BIRD dataset (Li et al., NeurIPS 2023)
- **Environment:** Windows 11, VSCode, venv at `venv/Scripts/activate`

---

## Project Structure
```
thesis_project/
├── data/bird/
│   ├── dev.json                          # 1,534 questions + gold SQL + evidence
│   ├── dev.sql
│   ├── dev_tables.json
│   ├── dev_sample_50.json                # Fixed 55-question reproducible test sample
│   └── dev_databases/                    # 11 SQLite databases
│       ├── california_schools/
│       ├── card_games/
│       ├── codebase_community/
│       ├── debit_card_specializing/
│       ├── european_football_2/
│       ├── financial/
│       ├── formula_1/
│       ├── student_club/
│       ├── superhero/
│       ├── thrombosis_prediction/
│       └── toxicology/
├── src/
│   ├── profiler/
│   │   ├── schema_profiler.py            # Extracts schema via PRAGMA
│   │   └── run_profiler.py               # Batch profiler for all 11 databases
│   ├── synthesiser/
│   │   ├── llm_synthesiser.py            # GPT generates semantic context JSON
│   │   └── run_synthesiser.py            # Batch synthesiser for all 11 databases
│   ├── agent/
│   │   ├── state.py                      # Shared AgentState TypedDict
│   │   ├── nodes.py                      # 4 nodes: context retrieval, SQL gen, executor, critic
│   │   └── graph.py                      # LangGraph graph assembly
│   └── evaluator/
│       ├── baseline.py                   # One-shot baseline (raw schema + evidence, no correction)
│       ├── ex_checker.py                 # Execution accuracy comparison
│       ├── harness.py                    # Full evaluation orchestrator with checkpoint/resume
│       ├── sample_questions.py           # Creates fixed 55-question test sample
│       └── analyse_results.py            # Per-database metrics from checkpoint files
├── outputs/
│   ├── semantic_context/                 # 11 raw_profile.json + 11 semantic_context.json
│   └── results/                          # Timestamped evaluation run folders
├── config.py                             # Paths, API keys, hyperparameters
├── requirements.txt
├── README.md                             # GitHub README with Mermaid flowchart
├── CLAUDE.md                             # This file
├── THESIS_MEETING_NOTES.md               # Meeting notes and findings
├── debug_ex.py                           # Debug script for EX checker
├── check_broken_questions.py             # Finds broken questions in european_football_2
└── .env                                  # API keys (never committed to git)
```

---

## System Architecture — Three Components

### Component 1 — Semantic Context Generator (offline, runs once)
- `schema_profiler.py` — opens SQLite file, runs PRAGMA commands to extract table names, column names, data types, PKs, FKs, sample values, value distributions. Saves as `*_raw_profile.json`
- `llm_synthesiser.py` — reads raw profile, sends to GPT, generates natural language descriptions, KPI flags, join paths. Saves as `*_semantic_context.json`
- These JSON files are permanent and reused for all questions — never regenerated during evaluation

### Component 2 — LangGraph Agentic Execution Engine (runs per question)
- `state.py` — defines `AgentState` TypedDict shared between all 4 nodes
- `nodes.py` — implements 4 nodes:
  - **Node A (context_retrieval):** reads semantic_context.json, sends question + full schema descriptions to GPT, returns focused list of relevant tables/columns
  - **Node B (sql_generator):** generates SQL from question + retrieved context + evidence (passed verbatim, NOT through Node A) + error history from previous failed attempts
  - **Node C (executor):** runs SQL against DuckDB. Success → END. Failure → logs error to state
  - **Node D (critic):** classifies error as SYNTAX/SEMANTIC/LOGIC, writes targeted correction instruction, routes back to Node B. Max 3 attempts (`MAX_CORRECTIONS` in config.py)
- `graph.py` — assembles nodes into LangGraph StateGraph with conditional edges

### Component 3 — Evaluation Framework
- `baseline.py` — one-shot GPT with raw schema + evidence, no semantic context, no correction loop
- `ex_checker.py` — runs predicted SQL and gold SQL against DuckDB, normalises results (lowercase, order-independent set comparison), checks match. Includes `normalise_sql_quotes()` to convert MySQL backticks to DuckDB double quotes
- `harness.py` — orchestrates full evaluation, saves checkpoint after every question, supports resume from crash. Uses fixed 55-question sample (`use_sample=True`) for development, full 1,534 for final runs
- `analyse_results.py` — reads checkpoint files, computes per-database EX and self-correction metrics

---

## API Configuration
- **API key variable:** `GEMINI_API_KEY` in config.py (misleadingly named — actually holds OpenAI key)
- **Current model:** `gpt-4o` for final evaluation, `gpt-4o-mini` for cheap development testing
- **Client:** `from openai import OpenAI; client = OpenAI(api_key=GEMINI_API_KEY)`
- **.env file format:**
```
  OPENAI_API_KEY=sk-...
  LLM_MODEL=gpt-4o
```

---

## Key Implementation Decisions and Bugs Already Fixed

### Evidence hints — CRITICAL architectural decision
- BIRD's `dev.json` has an `evidence` field per question — plain English hints about column meanings
- Evidence is passed to BOTH baseline and agent for fair comparison
- **CRITICAL BUG FIXED:** Evidence must be passed DIRECTLY to Node B, NOT only through Node A. Node A paraphrases/summarises context, which silently destroys precise values (e.g. rewrites `Segment = 'SME'` as `'Small and Medium Enterprises'`). Node B now receives evidence verbatim in addition to Node A's retrieved context.
- State field: `evidence: str` added to `AgentState`

### SQL quote normalisation
- BIRD gold SQL uses MySQL backtick quotes (`` ` ``) — DuckDB requires double quotes (`"`)
- `normalise_sql_quotes()` in `ex_checker.py` converts all backticks before execution
- Without this fix, all gold SQL fails and EX is always 0%

### DuckDB vs sqlite3 usage
- `sqlite3` (Python built-in) — used in profiler for schema extraction via PRAGMA
- `duckdb` — used in executor (Node C) and EX checker for SQL execution
- DuckDB connects directly to SQLite files: `duckdb.connect(str(db_path))`

### Checkpoint/resume system
- `harness.py` saves a `*_checkpoint.json` after every single question
- On restart, reads completed question IDs and skips them
- Critical for long runs — full evaluation takes 6-7 hours

### Fixed test sample
- `data/bird/dev_sample_50.json` — 55 questions (5 per database), fixed seed=42
- Always use `use_sample=True` in harness for development iteration
- Only use `use_sample=False` for final thesis evaluation runs

---

## Current Evaluation Results

### Full BIRD dev set (1,534 questions, GPT-4o, with evidence hints)
| Metric | Value |
|--------|-------|
| Baseline EX | 28.23% |
| Agent EX | 38.14% |
| Improvement | +9.91 pp |
| Self-correction rate | 68.6% |

### 55-question sample (latest run with evidence hints, improved prompts)
| Metric | Value |
|--------|-------|
| Baseline EX | ~54-56% |
| Agent EX | ~50-54% |
| Self-correction rate | ~66% |

Note: agent and baseline are close on the small sample — this is partly explained by the `european_football_2` data bug and small sample variance.

---

## Known Issues and Bugs

### european_football_2 data integrity bug — CRITICAL
- 48 of 129 questions (37.2%) reference `player_name`, `birthday`, `weight` on the `Player` table
- These columns DO NOT EXIST on `Player` in the distributed SQLite file
- They only exist on a separate table called `Player_old`
- BIRD's own gold SQL fails to execute on this database with `no such column: player_name`
- This affects BOTH baseline and agent equally — does not explain agent vs baseline gap
- **FIX NEEDED:** Either exclude these 48 questions, or patch the database by copying columns from `Player_old` to `Player`
- Script: `check_broken_questions.py` identifies all affected questions

### Misleadingly named variable
- `GEMINI_API_KEY` in `config.py` actually holds the OpenAI API key
- Reason: early development used Gemini, switched to OpenAI, variable name kept for simplicity
- Do NOT rename without updating all imports across nodes.py, baseline.py, synthesiser files

---

## Git Workflow
- **main branch** — stable, merged weekly
- **test-branch** — all active development
- Always work on `test-branch`, merge to main via pull request at end of week
- Activate venv before any work: `venv\Scripts\activate`

---

## Professor's Feedback and Requests

### From meeting (June 2026)
1. **Ablation study required** — isolate contribution of semantic context vs self-correction:
   - Condition A: Baseline (no context, no correction) — already implemented
   - Condition B: Context only (Node A + B + C, no correction loop, no Node D)
   - Condition C: Correction only (Node B + C + D with retry, but NO Node A — use raw schema like baseline)
   - Condition D: Full agent (Node A + B + C + D) — already implemented
2. **Include BIRD evidence hints** — done, both baseline and agent now receive evidence
3. **Check that percentages are not aggregated** — confirmed correct in harness.py (raw counts summed, percentage computed once at the end)

### Thesis structure feedback
- Merge theoretical background and related work into one chapter
- Structure by topic (benchmarks, metadata generation, agentic approaches, research gap)
- Prototypical implementation is sufficient — no need for production-ready system

---

## Next Steps (Priority Order)
1. **Fix european_football_2 database** — patch Player table with columns from Player_old
2. **Build 4-condition ablation study** — implement Condition B and C graph variants
3. **Improve synthesiser prompt** — add low-cardinality enum detection (fixes SME vs Small and Medium Enterprises type mismatches)
4. **Add few-shot examples to Node B** — one of highest-impact remaining improvements
5. **Implement McNemar's test** — statistical significance of improvement
6. **Final full evaluation run** — all 4 conditions, 1,534 questions, GPT-4o
7. **Thesis writing** — Chapters 1-5

---

## Key Papers to Reference
- [1] Biswal et al. (2026) — AgentSM: Semantic Memory for Agentic Text-to-SQL
- [2] Cao et al. (2026) — APEX-SQL
- [3] Chaturvedi et al. (2025) — SQL-of-Thought
- [4] Deng et al. (2025) — ReFoRCE
- [5] Gao and Luo (2025) — Automatic Database Description Generation
- [6] Hong et al. (2025) — Survey of LLM-based Text-to-SQL
- [7] Lei et al. (2025) — Spider 2.0
- [8] Li et al. (2023) — BIRD benchmark
- [9] Madaan et al. (2023) — Self-Refine
- [10] Pourreza and Rafiei (2023) — DIN-SQL
- [11] Shkapenyuk et al. (2025) — Automatic Metadata Extraction
- [12] Yang et al. (2026) — LLM-Based SQL Generation with self-refinement ceiling 66.3%

---

## How to Run

### Activate environment
```powershell
venv\Scripts\activate
```

### Run evaluation on 55-question sample (fast, cheap)
```powershell
python -m src.evaluator.harness
```

### Run full evaluation (slow, expensive — for final thesis results only)
Change `use_sample=True` to `use_sample=False` in `harness.py` bottom block, then run:
```powershell
python -m src.evaluator.harness
```

### Run single agent question (for debugging)
```powershell
python -m src.agent.graph
```

### Regenerate semantic context (after synthesiser prompt changes)
```powershell
python -m src.synthesiser.run_synthesiser
```

### Analyse latest results
```powershell
python -m src.evaluator.analyse_results
```