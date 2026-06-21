
---

## Files Used from BIRD

| File | Used? | Purpose |
|------|-------|---------|
| dev.json | YES | 1,534 questions + gold SQL + db_id |
| *.sqlite | YES | actual database files — profiled + queried |
| dev.sql | NO | not used |
| dev_tables.json | NO | not used |
| database_description/*.csv | NO | deliberately excluded — we generate these automatically |
| .DS_Store | NO | Mac system file, ignore |

---

---

## Complete Architecture Flow

**Component 1 — Semantic Context Generator (run once, offline)**

- `schema_profiler.py` — INPUT: .sqlite file → PRAGMA commands → OUTPUT: raw_profile.json
  - extracts: table names, column names, data types, Primary Keys, Foreign Keys, sample values, value distributions
- `run_profiler.py` — loops schema_profiler over all 11 databases
- `llm_synthesiser.py` — INPUT: raw_profile.json → GPT → OUTPUT: semantic_context.json
  - generates: table descriptions, column descriptions, KPI flags, join paths
- `run_synthesiser.py` — loops llm_synthesiser over all 11 databases

**Output:** 11 permanent JSON files in outputs/semantic_context/ — generated once, reused forever

---

**Component 2 — LangGraph Agentic Execution Engine (runs per question)**

- `state.py` — defines shared state object passed between all 4 nodes
- `nodes.py` — implements the 4 nodes
  - Node A: INPUT: question + semantic_context.json → OUTPUT: retrieved_context (relevant tables/columns)
  - Node B: INPUT: question + retrieved_context + error_history → OUTPUT: generated_sql
  - Node C: INPUT: generated_sql → DuckDB → OUTPUT: result (success) or error_message (failure)
  - Node D: INPUT: failed_sql + error_message → OUTPUT: error_type + correction_instruction → back to Node B
- `graph.py` — connects nodes into directed graph, defines routing logic

---

**Component 3 — Evaluation Framework**

- `baseline.py` — INPUT: question + raw schema only → GPT → SQL → DuckDB → result (no context, no retry)
- `ex_checker.py` — INPUT: predicted_sql + gold_sql → runs both → compares result tables → match True/False
- `harness.py` — orchestrates everything, loads dev.json, runs baseline + agent per question, saves checkpoints
- `analyse_results.py` — reads checkpoint files, computes per-database metrics

---

**Data flow summary**

- .sqlite files → schema_profiler → raw_profile.json → llm_synthesiser → semantic_context.json → Node A
- .sqlite files → Node C (executes generated SQL) → result
- .sqlite files → ex_checker (runs gold SQL) → comparison
- dev.json → harness → loads questions + gold SQL → feeds baseline and agent


## System Flow

> Question from BIRD dev.json

**BASELINE (one-shot)**
raw schema only → GPT → SQL → execute → result

**AGENT (4 nodes)**

- Node A — Context Retrieval: reads semantic_context.json → asks GPT which tables/columns are relevant
- Node B — SQL Generator: question + retrieved context + error history → GPT → SQL
- Node C — Executor: runs SQL against DuckDB → success = END, failure = Node D
- Node D — Critic: classifies error (SYNTAX / SEMANTIC / LOGIC) → targeted fix → back to Node B (max 3 attempts)

> EX Checker — compares both results against gold SQL result



## Results — Full BIRD Dev Set (1,534 questions, GPT-4o)

| Metric | Value |
|--------|-------|
| Baseline EX | 28.23% |
| Agent EX | 38.14% |
| Improvement | +9.91 pp |
| Self-correction rate | 68.6% |
| Agent exec failures | 5.0% vs 15.1% baseline |

Best database: superhero +23.3pp, SCR 100%
Worst database: thrombosis_prediction 10.4% — complex medical schema

---

## Why Baseline is 28% not ~46.35% (published)

- Published baselines use BIRD evidence hints — we deliberately exclude them
- We simulate true industrial cold-start — no human annotations
- Our baseline = stricter, more realistic setting
- Methodological choice, not a flaw

---

## Next Steps to Increase EX

### High impact, low effort
- Add BIRD evidence hints to prompts — biggest single gain, +5-10pp expected
- Fix prompt in Node B — always quote column names with spaces

### Medium impact, medium effort
- Minhash join path detection (AskData technique)
  - computes column value fingerprints across tables
  - discovers undocumented join paths automatically
  - adds to semantic context — better multi-table queries
- Richer semantic context — enumerate categorical values, add query patterns
- Few-shot examples in Node B prompt

### Statistical validation
- McNemar's test — confirms +9.91pp improvement is statistically significant
- Required before thesis submission

### Final evaluation
- Switch back to GPT-4o for final run
- Run all 1,534 questions once for thesis results

---

## Key Positioning vs Prior Work

| System | What it does | Our difference |
|--------|-------------|----------------|
| AgentSM | memory from execution traces | needs prior history — we work cold-start |
| APEX-SQL | profiles data at runtime per query | expensive — we generate context once offline |
| SEED | generates evidence per query | not reusable — ours is permanent |
| DIN-SQL | retries without classifying error | we classify SYNTAX/SEMANTIC/LOGIC first |
| AskData | automated metadata + Minhash | we add self-correcting agent loop on top |

---

## GitHub
https://github.com/Bhavya118/agentic-text-to-sql