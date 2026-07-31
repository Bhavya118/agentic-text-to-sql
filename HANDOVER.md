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

## ⚠️ CRITICAL RULE — API key / spending
**Never run, call, or otherwise trigger anything that hits the OpenAI API without the user explicitly asking for that specific run.** This includes `harness.py`, `baseline.py`'s `__main__` block, `nodes.py`'s `call_llm`, or any script that imports and invokes them. The `.env` file holds a real, paid OpenAI key and the user is budget-constrained. All code changes must be verified via **compile checks, graph-build checks, and offline logic tests on real local data (schema/JSON files) — never by actually invoking the LLM.** If verification requires an LLM call, ask first.

---

## Project Structure
```
thesis_project/
├── data/bird/
│   ├── dev.json                          # 1,534 questions + gold SQL + evidence
│   ├── dev.sql
│   ├── dev_tables.json
│   ├── dev_sample_50.json                # Fixed 55-question reproducible test sample (5 per DB × 11 DBs)
│   └── dev_databases/                    # 11 SQLite databases (european_football_2 patched — see below)
├── src/
│   ├── profiler/
│   │   ├── schema_profiler.py            # Extracts schema via PRAGMA (types, PK, FK, sample_values, value_distribution)
│   │   └── run_profiler.py               # Batch profiler for all 11 databases
│   ├── synthesiser/
│   │   ├── llm_synthesiser.py            # GPT generates semantic context JSON — STALE: still imports `google.genai`,
│   │   │                                   not migrated to OpenAI like the rest of the codebase. Don't run as-is.
│   │   └── run_synthesiser.py            # Batch synthesiser for all 11 databases
│   ├── common/                            # NEW (2026-07-30) — shared, dependency-free utilities, no LLM calls
│   │   ├── schema_utils.py               # get_raw_schema, find_columns, extract_missing_columns,
│   │   │                                   find_duplicate_columns, format_duplicate_columns
│   │   └── value_retrieval.py            # retrieve_matching_values, format_value_matches (fuzzy value grounding)
│   ├── agent/
│   │   ├── state.py                      # AgentState TypedDict — now includes include_raw_fallback flag
│   │   ├── nodes.py                      # 4 nodes + Condition-C's raw-schema node — see "Node behaviour" below
│   │   └── graph.py                      # Builds 3 graph variants: build_agent (D), build_condition_b_context_only,
│   │                                        build_condition_c_correction_only
│   └── evaluator/
│       ├── baseline.py                   # One-shot baseline (raw schema + evidence, no context, no correction)
│       ├── ex_checker.py                 # Execution accuracy — BIRD-faithful: order-sensitive WITHIN a row,
│       │                                    order-INsensitive ACROSS rows (confirmed against BIRD's official semantics)
│       ├── harness.py                    # Runs all 4 ablation conditions per question, checkpointed
│       ├── sample_questions.py           # Creates fixed 55-question test sample
│       └── analyse_results.py            # NOTE: does not actually exist in the repo despite being referenced
├── outputs/
│   ├── semantic_context/                 # 11 raw_profile.json + 11 semantic_context.json (permanent, reused)
│   └── results/                          # Timestamped run folders — see "Evaluation results" below
├── config.py                             # Paths, API keys, hyperparameters
├── requirements.txt
├── README.md
├── CLAUDE.md
├── THESIS_MEETING_NOTES.md               # Chronological, detailed research log — read this for exact evidence/citations
├── Code_Explaination.md                  # NEW (2026-07-30) — plain-language walkthrough of the codebase + today's changes
├── HANDOVER.md                           # This file
├── check_broken_questions.py             # european_football_2 debug script — issue now FIXED, script kept but stale
├── check_ef_fix.py / check_false_negatives.py / check_schema*.py / fix_ef_*.py / fix_european_football_db.py / verify_ef_fix.py
│                                          # More european_football_2 fix/debug scratch scripts — candidates for deletion,
│                                            not yet removed (needs explicit user confirmation, they're all git-tracked)
├── debug_ex.py / test_duckdb.py / test_llm.py
└── .env                                  # API keys (never committed to git)
```

---

## System Architecture — Three Components

### Component 1 — Semantic Context Generator (offline, runs once)
- `schema_profiler.py` — opens SQLite file, runs PRAGMA commands to extract table names, column names, data types, PKs, FKs, sample values, value distributions. Saves as `*_raw_profile.json`
- `llm_synthesiser.py` — reads raw profile, sends to GPT, generates natural language descriptions, KPI flags, join paths. Saves as `*_semantic_context.json`. **Note:** `semantic_context.json` never carried type/PK/sample-value info even before today — those only exist in `raw_profile.json`. Today's Node A fix merges both files at runtime rather than re-synthesising.
- These JSON files are permanent and reused for all questions — never regenerated during evaluation

### Component 2 — LangGraph Agentic Execution Engine (runs per question)
- `state.py` — `AgentState` TypedDict shared between all nodes. Added `include_raw_fallback: Optional[bool]` (2026-07-30) — controls whether Node B shows its raw-schema safety net / value hints / duplicate-column warnings. Defaults `True`; Condition C's entry node sets it `False` so its context stays equivalent to baseline's raw-schema-only view.
- `nodes.py` — implements:
  - **Node A (`node_context_retrieval`):** As of 2026-07-30, this is a **structured schema-linking selector**, not a free-text summarizer. It shows the LLM the full schema (with M-Schema-style enrichment: type, PK flag, description, KPI flag, sample values per column, merged from `raw_profile.json` + `semantic_context.json`), plus fuzzy-matched real database values (`value_retrieval.py`) and a duplicate-column-name ambiguity warning (`schema_utils.find_duplicate_columns`). The LLM must respond with **strict JSON**: `{"tables": {"ExactTableName": ["ExactColumnName", ...]}, "join_notes": "..."}`. A deterministic Python renderer (`_render_selection`) then builds the actual schema block Node B sees, using ONLY the selected identifiers, validated against the real schema — any hallucinated table/column name is silently dropped rather than rendered. Malformed JSON is caught by `_parse_selection` and degrades gracefully onto Node B's raw-schema fallback instead of crashing. The prompt also frames the task as "minimal sufficient set, justify against literal question text" rather than "relevant elements" (reduces over-inclusion).
  - **Condition C's entry point (`node_raw_schema_context`):** bypasses Node A entirely, feeds Node B the same raw schema the baseline sees, and sets `include_raw_fallback=False`.
  - **Node B (`node_sql_generator`):** generates SQL from question + Node A's rendered selection + evidence (passed verbatim) + error history. When `include_raw_fallback=True` (Conditions B & D, not C), it ALSO gets: the full raw schema as a safety net (in case Node A's selection missed something), fuzzy-matched real database values, and the duplicate-column ambiguity warning. Its rule list includes (added 2026-07-30): prefer `RANK()` over `ROW_NUMBER()` for ties, order SELECT columns to match question-mention order (BIRD's grading is column-order-sensitive within a row), and an explicit anti-over-join bias hint ("don't add a JOIN/table/condition that isn't strictly required"). `temperature=0` (was previously unset/default).
  - **Node C (`node_executor`):** runs SQL against DuckDB. Success → END. Failure → logs error to state. Unchanged today.
  - **Node D (`node_critic`):** classifies error as SYNTAX/SEMANTIC/LOGIC, writes a correction instruction, routes back to Node B (max 3 attempts). As of 2026-07-30, it also runs a **deterministic schema check** (`extract_missing_columns` + `find_columns`, zero LLM cost) before the LLM call — resolves "column not found" errors against the real schema and hands the critic ground truth instead of leaving it to parse/guess from the raw DuckDB error string.
- `graph.py` — assembles **three** graph variants (see Ablation study below), all sharing the same node functions.

### Component 3 — Evaluation Framework — now a 4-condition ablation study
- `baseline.py` (**Condition A**) — one-shot GPT with raw schema + evidence, no semantic context, no correction loop. As of 2026-07-30: `temperature=0`, and the same RANK-preference / column-ordering / anti-over-join rules as Node B (for fairness). Uses shared `get_raw_schema()` from `src/common/schema_utils.py` (deduplicated, used to define its own copy).
- **Condition B** (`build_condition_b_context_only` in `graph.py`) — Node A + B + C, correction loop removed entirely (executor → END regardless of outcome). Isolates Node A's contribution.
- **Condition C** (`build_condition_c_correction_only`) — Node A replaced by the raw-schema loader, Node B + C + D retry loop kept. Isolates Node D's contribution.
- **Condition D** (`build_agent`) — the full agent, all four nodes. This is "the agent" in casual conversation.
- `ex_checker.py` — runs predicted SQL and gold SQL against DuckDB. `normalise_sql_quotes()` converts MySQL backticks to DuckDB double quotes. **Confirmed (2026-07-30) this correctly replicates BIRD's own official grading**: order-sensitive WITHIN a row, order-insensitive ACROSS rows — not a bug, don't "fix" this to be more lenient, it's needed for external validity vs published BIRD numbers.
- `harness.py` — orchestrates all 4 conditions per question, checkpoints after every question (resume-safe), computes per-condition and aggregate EX + self-correction metrics. `CONDITION_BUILDERS` dict maps `context_only`/`correction_only`/`full_agent` → their graph builders. Uses fixed 55-question sample (`use_sample=True`) for development; full 1,534 for final runs only.
- `analyse_results.py` — **referenced in project structure docs but does not actually exist in the repo.**

---

## API Configuration
- **API key variable:** `GEMINI_API_KEY` in config.py (misleadingly named — actually holds OpenAI key). **See the critical rule above — never invoke this.**
- **Current model:** `gpt-4o` for evaluation
- **Client:** `from openai import OpenAI; client = OpenAI(api_key=GEMINI_API_KEY)`
- **.env file format:** `OPENAI_API_KEY=sk-...` / `LLM_MODEL=gpt-4o`

---

## Key Implementation Decisions and Bugs Already Fixed

### Evidence hints
- BIRD's `evidence` field is passed to BOTH baseline and agent for fair comparison.
- **Bug fixed (earlier session):** evidence must be passed DIRECTLY to Node B, not only through Node A, which paraphrases and can destroy precise values.

### SQL quote normalisation
- BIRD gold SQL uses backticks; `normalise_sql_quotes()` converts to double quotes for DuckDB. Without this, all gold SQL fails and EX is always 0%.

### european_football_2 data integrity bug — FIXED
- 48/129 questions referenced `Player.player_name`/`birthday`/`weight`, which only existed on `Player_old`. **Patched**: copied the missing columns from `Player_old` into `Player` (commit `6086de6`, before this session). All 129 gold SQL queries now execute. Confirmed still correctly resolves both `Player` and `Player_old(player_name)` as of 2026-07-30's schema-check testing.

### Node B lacked a raw-schema fallback (found + fixed 2026-07-30)
- Node B originally only ever saw Node A's *summarised* context — if Node A dropped a table/column, Node B had zero way to recover it, while baseline always saw the full unfiltered schema. Fixed: Node B now always gets a labelled raw-schema safety-net section too (when `include_raw_fallback=True`).

### Duplicate/collided column names across tables (found + fixed 2026-07-30)
- Root cause of a specific regression pattern: e.g. `thrombosis_prediction` has a genuinely real `Diagnosis` column on BOTH `Patient` and `Examination` — Node A silently pointed Node B at the wrong (but real) one. This is a name collision, not a hallucination, and the raw-schema-fallback fix doesn't help since the wrong column is present either way. Fixed via `find_duplicate_columns()` (excludes PKs and declared FK columns — those repeat by design) surfaced as an explicit warning to Node A and Node B.

### Node A was too willing to suggest a plausible-but-wrong alternative (found + partially fixed 2026-07-30)
- Beyond exact-name collisions, Node A would suggest a denormalized-but-differently-named column (`posts.OwnerDisplayName` vs `users.DisplayName`, both real) or an unnecessarily complex join (a double self-join in `toxicology`'s triple-bond question) — same underlying disease, broader than exact-name collision. Researched the literature (this is a known problem: "schema-linking over-inclusion / hallucinated joins" — see CHESS, RSL-SQL, E-SQL, C3). **Fixed**: Node A rewritten to output strict JSON (enumerated real identifiers only, not free prose) with a deterministic Python renderer that drops any hallucinated name; prompt reframed as "minimal sufficient set, justify against literal question text"; explicit anti-over-join bias hint added to Node B and baseline. **Not fixed**: bidirectional/backward verification and self-consistency at the retrieval stage — both would add a genuinely new LLM call per question (cost + latency), deliberately deferred rather than rushed in untested.

### RANK() vs ROW_NUMBER() (found + fixed 2026-07-30)
- The existing "ranking" rule offered both as interchangeable; they aren't (`RANK()` ties correctly, `ROW_NUMBER()` doesn't, and BIRD gold consistently uses `RANK()`). Tightened in both `nodes.py` and `baseline.py`.

### SELECT column ordering (found + fixed 2026-07-30)
- BIRD's EX metric is column-order-sensitive within a row (confirmed against BIRD's actual grading semantics — this is real, not this codebase's bug). Added an explicit rule to order SELECT columns matching question-mention order, in both `nodes.py` and `baseline.py`.

### Checkpoint/resume system
- `harness.py` saves a `*_checkpoint.json` after every question. **Note:** the per-question result schema changed 2026-07-30 (flat `agent_sql`/`agent_match` fields → nested `baseline`/`context_only`/`correction_only`/`full_agent` dicts) — old checkpoints are NOT compatible if you pass an old `run_id` to resume; only relevant for that specific resume path, fresh runs are unaffected.

### Fixed test sample
- `data/bird/dev_sample_50.json` — 55 questions (5 per DB), fixed seed=42. Always use `use_sample=True` for development; only `False` for final thesis runs.

---

## Evaluation results

### Historical full BIRD dev set (1,534 questions, GPT-4o) — STALE, do not cite
| Metric | Value |
|--------|-------|
| Baseline EX | 28.23% |
| Agent EX | 38.14% |

**This predates evidence hints and every fix made in this session — not a valid comparison point anymore.**

### 55-question ablation, run 1 (`eval_20260730_132134`) — before today's schema-linking fixes
| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 58.18% | — |
| B — Context only | 52.73% | −5.45pp |
| C — Correction only | 60.0% | +1.82pp |
| D — Full agent | 52.73% | −5.45pp |

### 55-question ablation, run 2 (`eval_20260730_145703`) — after today's fixes (structured Node A, duplicate-column warning, RANK/column-order/anti-over-join rules)
| Condition | EX | vs Baseline | Net Q gained/lost vs run 1 |
|---|---|---|---|
| A — Baseline | 54.55% | — | −2 (1 gained, 3 lost) |
| B — Context only | 54.55% | +0.00pp | +1 (2 gained, 1 lost) |
| C — Correction only | 54.55% | +0.00pp | −3 (0 gained, 3 lost) |
| D — Full agent | **61.82%** | **+7.27pp** | **+5 (5 gained, 0 lost)** |

**Full agent gaining 5 questions and losing 0 between the two runs is the cleanest result so far.** A/B/C landing at an identical total is coincidental (verified: per-database splits differ substantially; it's independent churn summing to the same number, not identical behaviour). Full detail, root-cause tracing of every individual flipped question, and the exact SQL diffs are in `THESIS_MEETING_NOTES.md` under 2026-07-30.

**Two benchmark/methodology quirks found, worth citing in the thesis limitations chapter, not chased as bugs:**
1. BIRD's EX metric is column-order-sensitive within a row (confirmed against official BIRD semantics) — a correct answer in a different column order scores 0.
2. DuckDB's `REAL` type is 32-bit float, not double. Gold SQL using `CAST(x AS REAL)` truncates precision; a mathematically-equivalent-but-full-double-precision expression (`x * 1.0`) can produce a *more accurate* value that still fails exact-string grading against a lower-precision gold value.

---

## Known Issues and Bugs

### Still open: Node A over-elaboration (partially mitigated, not eliminated)
Duplicate-column-name collisions are now flagged; denormalized-alternative-column confusion and over-elaborate joins (unrelated table names) are not caught by any current mechanism. Candidate fixes researched but not implemented (cost/time tradeoff): bidirectional/backward schema-linking verification (RSL-SQL), self-consistency at the retrieval stage.

### Misleadingly named variable
- `GEMINI_API_KEY` in `config.py` actually holds the OpenAI API key. Do NOT rename without updating all imports.

### llm_synthesiser.py is stale
- Still imports `from google import genai`, not migrated to OpenAI. Would fail if run today since `GEMINI_API_KEY` now holds an OpenAI-format key. Not run this session (semantic_context.json files are cached/permanent).

### analyse_results.py referenced but doesn't exist
- Mentioned in project structure docs (including this file, historically) but not present in `src/evaluator/`.

### european_football_2 debug scripts — cleanup still pending
- `check_broken_questions.py`, `check_ef_fix.py`, `check_false_negatives.py`, `check_schema*.py`, `fix_ef_*.py`, `fix_european_football_db.py`, `verify_ef_fix.py` are all scratch/debug scripts from the (now-fixed) european_football_2 patch. All git-tracked, safe to delete, but not yet removed — needs explicit user confirmation before a batch delete.

---

## Git Workflow
- **main branch** — stable, merged weekly
- **test-branch** — all active development
- Always work on `test-branch`, merge to main via pull request at end of week
- Activate venv before any work: `venv\Scripts\activate`

---

## Professor's Feedback and Requests

### From meeting (June 2026) — status update
1. **Ablation study — DONE.** All 4 conditions (A/B/C/D) built and run twice on the 55-question sample. See "Evaluation results" above.
2. **Include BIRD evidence hints — done** (earlier session), both baseline and agent receive them.
3. **Check that percentages are not aggregated — confirmed correct** in `harness.py` (raw counts summed, percentage computed once at the end).

### Thesis structure feedback
- Merge theoretical background and related work into one chapter.
- Structure by topic (benchmarks, metadata generation, agentic approaches, research gap).
- Prototypical implementation is sufficient — no need for production-ready system.

---

## Next Steps (Priority Order)
1. **Meeting with Prof. Höpken on 2026-07-31** — bring the ablation results, the root-cause narrative (schema-linking over-inclusion, self-correction's blindness to non-throwing errors), and the two benchmark-methodology quirks found.
2. **Decide on Tier 3 improvements** (from research, not yet implemented): bidirectional schema-linking verification, self-consistency multi-candidate voting — both add real API cost, need explicit budget decision.
3. **Few-shot examples in Node B** — needs BIRD's *train* split (not present locally, `data/bird/` only has `dev.json`). Deliberately NOT sourced from dev-split questions — would undermine the thesis's cold-start positioning vs AgentSM in the related-work table.
4. **Implement McNemar's test** — statistical significance of improvement, required before thesis submission.
5. **Final full evaluation run** — all 4 conditions, 1,534 questions, GPT-4o. Expensive — needs explicit go-ahead each time.
6. **Clean up european_football_2 debug scripts** — pending user confirmation.
7. **Thesis writing** — Chapters 1-5.

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
- [13] **NEW** Talaei et al. (2024) — CHESS: Contextual Harnessing for Efficient SQL Synthesis (schema linking precision/recall, value retrieval via LSH)
- [14] **NEW** Pourreza et al. — CHASE-SQL: Multi-Path Reasoning and Preference Optimized Candidate Selection (arXiv:2410.01943)
- [15] **NEW** XiYan-SQL: A Multi-Generator Ensemble Framework (arXiv:2411.08599) — M-Schema representation, skeleton-similarity few-shot selection
- [16] **NEW** Cao et al. — RSL-SQL: Robust Schema Linking (arXiv:2411.00073) — bidirectional verification, 94% recall / 83% column reduction
- [17] **NEW** ErrorLLM: Modeling SQL Errors for Text-to-SQL Refinement (arXiv:2603.03742) — only ~3% of incorrect SQL raises execution errors; directly validates this thesis's Node D blind-spot finding
- [18] **NEW** Dong et al. — C3: Zero-shot Text-to-SQL with ChatGPT (arXiv:2307.07306) — named-bias calibration hints
- [19] **NEW** E-SQL: Direct Schema Linking via Question Enrichment (arXiv:2409.16751)
- [20] **NEW** MCS-SQL: Multiple Prompts and Multiple-Choice Selection (arXiv:2405.07467)

---

## How to Run

### Activate environment
```powershell
venv\Scripts\activate
```

### Run evaluation on 55-question sample, all 4 conditions (fast-ish, still real money — ask before running)
```powershell
python -m src.evaluator.harness
```

### Run full evaluation (slow, expensive — final thesis results only, explicit go-ahead required every time)
Change `use_sample=True` to `use_sample=False` in `harness.py`'s bottom block.

### Run single agent question (for debugging — still calls the API, ask first)
```powershell
python -m src.agent.graph
```

### Regenerate semantic context (after synthesiser prompt changes)
`llm_synthesiser.py` is currently stale (Gemini client, OpenAI key) — would need migrating to `openai.OpenAI` before this works.
