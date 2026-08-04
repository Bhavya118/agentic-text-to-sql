
---

## Files Used from BIRD

| File | Used? | Purpose |
|------|-------|---------|
| dev.json | YES | 1,534 questions + gold SQL + db_id |
| *.sqlite | YES | actual database files - profiled + queried |
| dev.sql | NO | not used |
| dev_tables.json | NO | not used |
| database_description/*.csv | NO | deliberately excluded - we generate these automatically |
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
  - Node B: INPUT: question + retrieved_context + Evidence + error_history → OUTPUT: generated_sql
  - Node C: INPUT: generated_sql → DuckDB → OUTPUT: result (success) or error_message (failure)
  - Node D: INPUT: failed_sql + error_message → OUTPUT: error_type + correction_instruction → back to Node B
- `graph.py` — connects nodes into directed graph, defines routing logic

---

**Component 3 — Evaluation Framework**

- `baseline.py` — INPUT: question + raw schema only + Evidence → GPT → SQL → DuckDB → result (no context, no retry)
- `ex_checker.py` — INPUT: predicted_sql + gold_sql → runs both → compares result tables → match True/False
- `harness.py` — orchestrates everything, loads dev.json, runs baseline + agent per question, saves checkpoints


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


---

## Key Findings This Week

1. Evidence hints injected only into Node A's context-retrieval step degraded agent accuracy, because Node A paraphrases schema context and silently loses precise values (e.g. rewriting `'SME'` as `'Small and Medium Enterprises'`) - fixed by passing evidence verbatim directly to the SQL generation node.

2. A subset of accuracy losses stem not from incorrect query logic but from unstated conventions in BIRD's gold annotations, such as implicitly excluding NULL values from "list" queries even when not explicitly requested - meaning part of the EX gap reflects benchmark annotation style rather than genuine reasoning failure.

3. Prompt refinements fall into two categories: general-purpose fixes (e.g. translating evidence pseudo-code into valid SQL, preventing the correction loop from repeating identical failed fixes) likely to generalize to real industrial schemas, versus benchmark-specific conventions that may not transfer to other domains - a limitation worth noting for real-world generalizability claims.

4. Discovered a genuine data integrity bug in the BIRD benchmark itself: 48 of 129 questions (37.2%) in the `european_football_2` database reference a `player_name` column on the `Player` table that does not exist there (it is only on a separate `Player_old` table) - confirmed by showing BIRD's own gold SQL fails to execute, meaning part of the accuracy gap on this database is a benchmark data issue, not a system limitation.


---

## Accuracy Experiments — Current Status

- Created a fixed, reproducible 55-question sample (5 per database x 11 databases) for fast iteration without running the full 1,534-question set every time

- Added BIRD evidence hints to both baseline and agent prompts (as requested) - isolates the comparison from "who has more information"

- Progression of agent vs baseline on the 55-question sample as fixes were applied:
  - No evidence, original prompts: Agent 38.14% vs Baseline 28.23% (full 1,534 set)
  - Evidence added, bug in Node A (evidence lost via paraphrasing): Agent 34-40% vs Baseline 54-56% - agent regressed
  - Fixed: evidence passed directly to Node B, NULL-exclusion rule, pseudo-code translation rule added: Agent 54.55% vs Baseline 49.09% (agent-only improvements)
  - Same rules added to baseline for fairness: Agent 50.91% vs Baseline 56.36% - still investigating this gap, partly explained by small-sample variance and the european_football_2 data bug

- Open question: with both systems given equal evidence and equal prompt quality, does the agent's architecture (semantic context + self-correction) still add value? This is the core ablation question - not yet conclusively answered on the small sample, full ablation study (4 conditions) still needed

- Next: patch or exclude the 48 broken european_football_2 questions, re-run clean comparison, then build the 4-condition ablation study (context-only, correction-only, both, neither)

---

## 2026-08-04

### What changed since the last full run (baseline 28.23% / agent 38.14%)

- Built the two missing ablation conditions — **B: context only**, **C: correction only** — alongside baseline (A) and full agent (D). Full 4-condition framework now complete, as requested.
- Fixed Node B never falling back to the raw schema when context retrieval dropped a needed column.
- Added **value grounding** — fuzzy-matches question entities against real database values, so filters use exact stored values instead of guessed wording/casing.
- Added **duplicate-column collision detection** — flags column names that exist identically on more than one table (e.g. `Diagnosis` on two unrelated tables) and warns the model to disambiguate.
- **Rewrote schema linking to output structured, validated selections instead of free text** — the model can no longer describe a plausible-but-wrong join or column as if it were the obvious choice; any invented name is dropped automatically.
- Added ranking-function, column-ordering, and anti-unnecessary-join fixes — applied identically to baseline and agent prompts for fairness.
- Every fix verified offline (schema/data checks, unit tests) before any paid evaluation run.

---

### 55-question ablation (development sample)

| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 54.55% | — |
| B — Context only | 54.55% | +0.00pp |
| C — Correction only | 54.55% | +0.00pp |
| D — Full agent | **61.82%** | **+7.27pp** |

- Full agent moved from *underperforming* baseline (−5.45pp, before fixes) to a clear lead (+7.27pp).
- **McNemar's exact test on this result: p = 0.34 — not significant.** Directionally positive, mechanistically explained, but the sample is too small to prove it statistically on its own.
- Purpose of this sample: fast, cheap iteration to find and fix bugs before committing to the full run.

---

### Full 1,534-question evaluation (final)

| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 49.93% | — |
| B — Context only | 52.09% | +2.15pp |
| C — Correction only | 52.02% | +2.09pp |
| D — Full agent | **54.24%** | **+4.30pp** |

**McNemar's exact test, each condition vs baseline:**

| Condition | Discordant pairs | Win/loss split | p-value | Significant? |
|---|---|---|---|---|
| B — Context only | 167 | 100 / 67 | 0.013 | Yes |
| C — Correction only | 114 | 73 / 41 | 0.0035 | Yes |
| D — Full agent | 178 | 122 / 56 | **8.4×10⁻⁷** | **Yes, decisively** |

### Analysis

- **All three conditions now significantly beat baseline.** The 55-question pilot showed the right direction but couldn't prove it; full-scale data does.
- Baseline (49.93%) is already above BIRD's own published GPT-4 zero-shot reference point (46.35%, same evidence-hint setup); the full agent adds another +4.3pp on top of that.
- **Self-correction quality**: correction triggers on only ~8–11% of questions (most wrong SQL never throws an error), and of those, only ~21–26% become genuinely correct — the rest execute cleanly but are still wrong. Confirms the literature finding (ErrorLLM) that error-triggered correction has a hard ceiling, now backed by ~150-160 real triggered cases instead of a handful.
- **Case study — `card_games`** (largest DB, 191 questions): flat result (45.0%→45.0%) is not "no effect" — it's two equal, opposite effects cancelling. Semantic context correctly fixes several table-name confusions baseline makes (e.g. treating a set name as a card name); it simultaneously introduces one new, specific bug — joining `cards`↔`foreign_data` via `multiverseId` instead of the actual declared foreign key `uuid` (confirmed: the `uuid` join returns 229,170 correctly-matched rows, the `multiverseId` join returns only 14 — a near-broken join that still executes without error).

---

### Next steps

1. **Fix the `card_games` join-key issue** — surface real declared foreign keys explicitly (already collected by the schema profiler, currently unused downstream) instead of relying on the LLM's guessed join paths. No new API cost to implement; cheap to validate on the ~11 known-affected questions rather than a full re-run.
2. Statistical significance is now established at full scale — ready to write into the thesis results chapter.
3. Few-shot examples in Node B — needs a held-out BIRD training split (not yet available locally), kept separate from the evaluation set to preserve the system's cold-start positioning.
4. Bidirectional schema-linking verification and self-consistency voting — both identified in earlier research as the next-most-promising fixes, both require an additional model call per question. Deferred pending budget.
5. **Budget note:** cumulative API spend is approaching the 100 EUR university reimbursement ceiling. Remaining work defaults to free/cheap validation (offline checks, tiny targeted samples); another full 1,534-question run should only happen once, deliberately, for final thesis submission numbers.
6. european_football_2 debug scripts still pending cleanup (fix is committed, scripts are just clutter).