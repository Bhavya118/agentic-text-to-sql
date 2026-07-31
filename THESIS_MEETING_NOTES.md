
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

## 2026-07-30

### Context
- Meeting with Prof. Höpken scheduled for 2026-07-31. Went in needing an answer for why agent EX was tracking at or below baseline on the 55-question sample (50.91% vs 56.36% in the `eval_20260622_000408` run), and a concrete plan to fix it.
- european_football_2 database patched (Player table now has player_name/birthday/weight copied from Player_old) — committed, all 129 gold SQL queries in that database now execute.

### Root-cause hypotheses identified from code review
1. **Node B had no raw-schema fallback.** `node_sql_generator` only ever received Node A's *summarised* semantic context, never the raw schema. If Node A dropped a table/column while summarising, Node B had no way to recover it — whereas the baseline always sees the *full*, unfiltered raw schema. This is a plausible explanation for cases like `formula_1` (baseline 100% vs agent 80% on the 55-question sample): a small schema where filtering can only hurt, never help.
2. **The correction loop is blind to silent logical errors.** Node D only fires when `execution_error` is set. A query that runs cleanly but returns the wrong answer — no syntax error, just wrong logic — never triggers a correction. This is a structural blind spot in the current architecture, not yet fixed (would need self-consistency voting across multiple candidate SQLs, or a result-plausibility critic pass even on execution success — both add API calls, deferred pending budget decision).
3. `call_llm` never set `temperature`, so every node was running at the OpenAI default (non-zero) — reducing determinism on a task where consistency should help.

### Fixes applied (code only — zero API calls made while implementing/verifying)
1. Added `src/common/schema_utils.py` with a shared `get_raw_schema()`, deduplicated out of `baseline.py`.
2. Node B now always receives the full raw schema as a labelled safety-net section alongside Node A's retrieved context, so it can no longer lose visibility into a column/table Node A dropped.
3. `temperature=0` added to every LLM call (all agent nodes + baseline).

### Ablation study built (per Prof's request from the June 2026 meeting)
- Condition A — baseline (already existed, unchanged).
- Condition B — context only: Node A + B + C, correction loop removed entirely (`build_condition_b_context_only` in `graph.py`) — isolates Node A's (semantic context) contribution.
- Condition C — correction only: Node A replaced with a raw-schema loader (`node_raw_schema_context`), Node B + C + D retry loop kept (`build_condition_c_correction_only` in `graph.py`) — isolates Node D's (self-correction) contribution.
- Condition D — full agent (already existed, unchanged).
- `harness.py` rewired to run and checkpoint all 4 conditions per question, computing per-condition and aggregate EX + self-correction metrics.
- Verified all three graphs build/compile correctly and `compute_metrics` produces correct per-condition output against hand-built fake data — confirmed with no real OpenAI calls.

### Not yet done
- Have NOT run the 55-question × 4-condition ablation yet — needs a real, paid evaluation run, deliberately not executed by Claude (API key is off-limits per instruction, all spend decisions stay with me).
- european_football_2 debug/fix scripts (`check_ef_fix.py`, `fix_ef_id.py`, `verify_ef_fix.py`, etc.) still sitting in repo root — the fix itself is committed, scripts are cleanup candidates, not yet removed.

### Next steps
1. Decide whether to spend on running the 55-question, 4-condition ablation before tomorrow's meeting, or present the root-cause hypothesis + fix + ablation design as the story if there isn't time/budget.
2. If run: compare Condition B vs D to isolate Node A's contribution, Condition C vs D to isolate Node D's contribution, and check whether the Node B raw-schema-fallback fix closes the baseline gap seen in the `eval_20260622_000408` run.
3. Still pending from earlier weeks: few-shot examples in Node B, McNemar's significance test, final full 1,534-question run, self-consistency/result-plausibility check for silent logical errors.

### Research: what top BIRD leaderboard systems do differently
Researched current top-performing BIRD systems (CHASE-SQL 73.0% EX, XiYan-SQL 75.6% EX, MCS-SQL, DIN-SQL, DAIL-SQL, CHESS) to see which of their techniques are adoptable here. Key finding worth citing directly: **ErrorLLM (arXiv:2603.03742)** measured that syntax/execution errors account for only ~3% of incorrect SQL queries — the rest execute successfully but are semantically wrong (execution-based self-debugging gets 100% precision but only 2.95–6.50% recall on real error sets). This is hard, citable, external validation of the Node D blind spot identified earlier today (correction loop only fires on `execution_error`, structurally blind to silently-wrong SQL).

Techniques triaged into tiers by cost/effort — full breakdown with sources kept in the chat session, condensed list:
- **Tier 1 (free/near-free, implemented today)**: value retrieval (CHESS/XiYan-SQL/CHASE-SQL), M-Schema-style prompt formatting (XiYan-SQL), rule-based schema pre-check before the LLM critic (PV-SQL/LitE-SQL style).
- **Tier 2 (cheap, not yet implemented)**: few-shot examples via masked/skeleton-similarity retrieval (DAIL-SQL, XiYan-SQL) — same idea as the pre-existing "add few-shot examples" next step, now with a concrete retrieval method behind it.
- **Tier 3 (moderate–high cost, not yet implemented)**: explicit error-type/plausibility detection instead of relying on execution errors (ErrorLLM), self-consistency multi-candidate voting (CHASE-SQL/XiYan-SQL/MCS-SQL) — the two techniques that would most directly close the Node D blind spot, but both add real API cost (self-consistency is N× Node B calls).

### Tier 1 implementation (code only, zero API calls made)
1. **Value retrieval/grounding** (`src/common/value_retrieval.py`, new) — fuzzy-matches entities in the question/evidence against real column values already collected by `schema_profiler.py` (`sample_values` + `value_distribution` in `*_raw_profile.json`) using stdlib `difflib`, no embeddings, no LLM call. Injected into Node A's prompt and Node B's prompt (the latter gated by `include_raw_fallback`, so Condition C stays a clean "raw-schema-only" comparison). Verified against a real question ("Fresno county" → correctly matched `County Name`/`cname`/`County`/`City`/`MailCity` = 'Fresno' across 3 tables in `california_schools`).
2. **M-Schema-style formatting for Node A** — `node_context_retrieval` now cross-references `*_raw_profile.json` at runtime and merges data type, primary-key flag, and example values into each column line alongside the synthesised description/KPI flag/notes, instead of description-only prose. No re-synthesis of the semantic context JSONs needed (those still lack type/PK/samples entirely — confirmed by inspecting the actual files).
3. **Deterministic schema pre-check for Node D** — new `find_columns()` / `extract_missing_columns()` in `src/common/schema_utils.py`. Before the critic's LLM call, "column not found" errors are parsed and cross-checked against the real schema in plain Python; the correct table(s) are handed to the critic as ground truth instead of leaving it to parse/guess from the raw DuckDB error string. Verified against the (now-patched) european_football_2 database: a synthetic "player_name not found" error correctly resolved to `Player_old(player_name), Player(player_name)`.
- Deliberately **not** applied to `baseline.py` — value grounding and M-Schema formatting are semantic-context enrichments, and baseline is intentionally the unenriched comparison point by design.
- All three verified via direct calls to the real profiler/schema data (california_schools, european_football_2) and full graph-build checks — no OpenAI API calls made.

### Next: run the 55-question, 4-condition ablation with Tier 1 fixes included, to get first real numbers ahead of tomorrow's meeting (pending approval to spend).

### 55-question, 4-condition ablation results (run `eval_20260730_132134`, with Tier 1 fixes included)

| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 58.18% | — |
| B — Context only (Node A, no correction) | 52.73% | −5.45pp |
| C — Correction only (raw schema, no Node A) | 60.0% | +1.82pp |
| D — Full agent (Node A + correction) | 52.73% | −5.45pp |

**Key finding: the regression isolates cleanly to Node A, not to the correction loop.** Conditions B and D score identically on 9 of 11 databases — Node D contributes almost nothing extra when Node A is in the pipeline. Condition C (correction loop alone, no Node A) is the only agent variant that beats baseline. Tier 1's raw-schema-fallback fix (added this morning) did not fix this, because it targets *missing* schema information — the actual failure mode found here is different.

**Root cause, confirmed against the real schema:** in `thrombosis_prediction`, baseline correctly queries `Patient.Diagnosis`; context-only and full-agent both query `Examination.Diagnosis` instead. Checked the real schema — **both tables genuinely have a column named `Diagnosis`.** Node A isn't hallucinating a nonexistent column, it's pointing Node B at the wrong one of two real, identically-named columns across tables. A second example in `toxicology` (triple-bond question) shows Node A's join-path description leading Node B into an unneeded double self-join, producing the wrong output shape — again with no execution error, so invisible to Node D. Both are column/schema **collisions**, not omissions.

**The self-correction-rate metric is currently overstating itself.** As defined in `compute_metrics`, `self_corrected` means "attempts > 1 AND execution succeeded" — not "attempts > 1 AND now correct." Recomputed properly from this run's data:
- Condition C: correction triggered on 5/55 questions → 2 became genuinely correct, 3 were fixed into a *different wrong-but-executing* query.
- Condition D: triggered on only 3/55 → 1 genuinely correct, 2 executes-but-wrong.

This directly reproduces the ErrorLLM finding from last night's research in our own data: the correction loop reliably fixes queries that throw errors, but a large share of wrong SQL just executes cleanly and Node D never sees it. Worth noting as a metric-definition caveat in the thesis methodology, and worth reporting a "genuinely corrected" rate alongside the current execution-based one.

**Proposed next fix (not yet implemented):** detect column names that collide across multiple tables using data already in `raw_profile.json` (zero API cost), and inject an explicit disambiguation warning into Node A's and Node B's prompts whenever a question touches one of them — directly targeting the `Diagnosis`-style collision above.

### Duplicate-column disambiguation fix (implemented, code only, zero API calls)
- New `find_duplicate_columns()` / `format_duplicate_columns()` in `src/common/schema_utils.py`: scans the real schema via `sqlite3` PRAGMA and flags column names that appear identically on 2+ tables, **excluding** primary keys and columns that participate in a declared foreign key (those repeat by name intentionally — e.g. `raceId` across 5 `formula_1` tables — and would just be noise).
- Verified the filtered list on real data: `thrombosis_prediction` → exactly `Diagnosis: [Examination, Patient]` (the smoking-gun case from tonight's ablation), `toxicology` → empty (0, matches that its regression was a join-shape problem, not a name collision — see below), `california_schools` → empty. Before FK-exclusion, `formula_1`/`european_football_2` had 11–14 noisy entries (mostly FK join keys); after exclusion, down to 6–11 genuinely meaningful ones (e.g. `european_football_2`: `player_name`/`birthday`/`height`/`weight` duplicated across `Player`/`Player_old`, `date` across 3 unrelated tables).
- Wired into Node A's prompt (always) and Node B's prompt (gated by `include_raw_fallback`, so Condition C stays a clean raw-schema-only comparison, same pattern as the value-retrieval and raw-schema-fallback fixes). Node B's rule list now explicitly instructs it to pick the table matching question intent, not the first match, when a flagged column is in play.
- Note: this fix targets the `thrombosis_prediction` failure mode specifically (name collision across tables). It does **not** address the `toxicology` triple-bond failure mode (Node A leading Node B into an unnecessary double self-join via `connected.atom_id`/`atom_id2`) — that's a join-path reasoning error, not a column collision, and remains open.
- All verified via direct calls against real `.sqlite` files and a full graph-build check — no OpenAI API calls made.

### Full regression audit across all 11 databases (not just the 2 spot-checked earlier)
Checked every question where baseline matched gold but an agent variant (context-only/full-agent) didn't: 6 out of 55. Categorised each:

| DB | Root cause | Covered by duplicate-column fix? |
|---|---|---|
| thrombosis_prediction | `Examination.Diagnosis` vs `Patient.Diagnosis` — exact-name collision | Yes |
| california_schools | Correct columns, wrong SELECT order (`City, School, Low Grade` vs gold's `City, Low Grade, School`) | No — not a collision, see below |
| superhero | `ROW_NUMBER()` used where gold uses `RANK()` — same rows, different values on ties | No — prompt wording bug |
| codebase_community | Used `posts.OwnerDisplayName` (real, denormalized) instead of `users.DisplayName` | No — different column names, same disease |
| european_football_2 | Over-elaborate join through `Player` to filter `Player.id` instead of `Player_Attributes.id` directly | No — join-shape reasoning, not a collision |
| toxicology | Double self-join via `atom_id`/`atom_id2`; gold only joins one side | No — same over-elaboration pattern |

**Only 1 of 6 is addressed by the duplicate-column fix.** Two more turned out to be separate, equally cheap issues (now fixed, see below). The remaining 3 (codebase_community, european_football_2, toxicology) confirm a broader, still-open pattern: Node A is generally too willing to suggest a plausible-but-wrong alternative (a denormalized column, an extra join hop) instead of the simplest correct path — a harder problem than exact-name collision, not resolved tonight.

**Important methodology finding, not a bug:** researched BIRD's official execution-accuracy metric — confirmed it is column-*order*-sensitive within a row (order-insensitive across rows), and this codebase's `ex_checker.py` already correctly replicates that. The california_schools case above is a legitimate (if arguably harsh) BIRD grading behavior, not a measurement artifact — worth citing as a known benchmark strictness in the thesis's methodology/limitations discussion. [Source: motherduck.com/blog/bird-bench-and-data-models]

### Two more cheap prompt fixes implemented (code only, zero API calls)
1. **RANK() vs ROW_NUMBER()** — the existing "ranking" rule in both `nodes.py` and `baseline.py` offered `ROW_NUMBER()` and `RANK()` as interchangeable; they aren't (`RANK()` ties correctly, `ROW_NUMBER()` doesn't, and gold consistently uses `RANK()`). Tightened both files to prefer `RANK()`, matching the superhero regression found above.
2. **SELECT column ordering** — added a rule to both `nodes.py` and `baseline.py` instructing the SQL generator to order SELECT columns in the same sequence entities are mentioned in the question, since BIRD's grading is order-sensitive (see above). Applied to both baseline and agent for fairness.
- Verified via compile checks and full graph-build — no OpenAI API calls made.

### Next: second 55-question ablation run tonight with all fixes included (raw-schema fallback, value retrieval, M-Schema formatting, duplicate-column warning, RANK preference, SELECT column ordering), to get final numbers for tomorrow's meeting.

### Research: how to fix "Node A too willing to suggest a plausible-but-wrong alternative"
Researched the specific failure pattern found in the regression audit above (this is a known, named problem in the literature: schema-linking over-inclusion / hallucinated joins). Five candidate fixes identified, ranked by cost and directness:
- **(A) Force structured JSON output instead of free prose** — every top system (CHESS, XiYan-SQL, E-SQL) has Node A output a strict enumerated list of real identifiers, not a descriptive paragraph; a separate deterministic step renders the actual schema block. Zero extra API cost (same single call, different output format).
- **(B) Bidirectional/backward verification** (RSL-SQL, arXiv:2411.00073) — after forward retrieval, verify each candidate actually connects back to the question; reports 94% recall while cutting 83% of over-included columns. Costs one extra LLM call per question.
- **(C) Reframe the prompt as "minimal sufficient set"** rather than "relevant elements" — zero cost, pure wording change.
- **(D) Explicit named-bias calibration** (C3, arXiv:2307.07306) — telling the model to avoid a specifically-named bias (e.g. unnecessary joins) beats generic caution. Zero cost.
- **(E) Self-consistency at the retrieval stage** — run Node A twice, keep only tables/columns both runs agree on. Costs one extra LLM call per question.

**Decision: implemented A, C, D tonight; deliberately skipped B and E.** Honest reasoning, not "these will definitely help": A/C/D add zero API cost and their logic is fully testable offline before spending anything. B and E both add a genuinely new LLM call per question — more cost, more latency on an already slow run (~30-160s/question seen earlier tonight), and no way to validate the actual LLM behavior without spending API budget on test calls, hours before the one evaluation run available before tomorrow's meeting. Rather than bundle in two untested new call-stages under time pressure, held them back for a future, properly-validated pass.

### Implemented: structured Node A rewrite + anti-over-join bias hints (code only, zero API calls)
1. **Node A now outputs strict JSON, not prose.** `node_context_retrieval` in `nodes.py` prompts for `{"tables": {"ExactTableName": ["ExactColumnName", ...]}, "join_notes": "..."}` instead of a free-text "context block." New `_parse_selection()` handles markdown-fenced or malformed JSON gracefully (returns `None` rather than crashing). New `_render_selection()` deterministically builds the schema block Node B sees, pulling real metadata from `raw_profile.json`/`semantic_context.json` for ONLY the selected pairs — any hallucinated table/column name Node A invents is silently dropped rather than rendered, closing off the "free text = room to invent a plausible join" surface found in tonight's audit.
2. **Defensive fallback chain**: malformed JSON → generic parse-failure message; valid JSON but every table/column hallucinated → "no valid selection" message. Both degrade gracefully onto Node B's existing raw-schema safety net rather than crashing the run. Caught and fixed one real bug during testing: the fallback message wasn't triggering on total hallucination because join-path reference text was being appended after the emptiness check — fixed to check before.
3. **Minimal-set framing (C)**: Node A's prompt now explicitly requires justifying every table/column against a literal word or phrase in the question, not "relevance."
4. **Anti-over-join bias hint (D)**: added "do not add a JOIN, table, or extra condition that isn't strictly required... prefer the simplest query" to both `nodes.py`'s Node B rules and `baseline.py`, for fairness.
- Verified via 10 hand-built test cases against real california_schools data (clean JSON, markdown-fenced JSON, malformed text, hallucinated table, hallucinated column, empty selection, missing keys) — all pass. Full compile + graph-build check also passed. No OpenAI API calls made at any point tonight.

**Caveat for the record:** this is a genuinely bigger change than tonight's earlier fixes, stacked into the same run as everything else — scientifically messier to attribute if the numbers move (won't know which specific change did what), but accepted as a disclosed tradeoff given the time constraint before tomorrow's meeting.

### Second 55-question, 4-condition ablation run (`eval_20260730_145703`), with all of tonight's fixes included

| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 54.55% | — |
| B — Context only | 54.55% | +0.00pp |
| C — Correction only | 54.55% | +0.00pp |
| D — Full agent | **61.82%** | **+7.27pp** |

**Headline: full-agent swung from −5.45pp (previous run) to +7.27pp — a 12.7pp turnaround**, and it's explainable, not just noise. Verified via `debit_card_specializing`: 3 of 5 questions flipped wrong→right, each attributable — a real baseline date-range bug (`SUBSTR(Date,1,4) BETWEEN '201301' AND '201312'`, a string-comparison bug that matches nothing) that full-agent avoided; a simpler, correct aggregation where baseline over-complicated the query; and one clean confirmation of the value-retrieval fix — baseline guessed `Currency = 'euro'` (wrong casing), full-agent correctly used the real value `'EUR'`, which baseline never gets grounding for by design.

**A/B/C landing at the identical 54.55% total is coincidental, not a sign nothing changed.** Computed net question-level churn between the two runs per condition:

| Condition | Gained | Lost | Net |
|---|---|---|---|
| A — Baseline | 1 | 3 | −2 |
| B — Context only | 2 | 1 | +1 |
| C — Correction only | 0 | 3 | −3 |
| D — Full agent | 5 | 0 | **+5** |

Each condition arrived at its total through different, independent question-level movement — the equal totals for A/B/C are a coincidence of this specific 55-question sample. D gaining 5 and losing 0 is the cleanest result in the whole run: zero regressions.

**Important correction to the working narrative: tonight's changes were NOT isolated to Node A ("the context layer").** Three new rules (RANK preference, SELECT column ordering, anti-over-join bias) were added directly to Node B's (`node_sql_generator`'s) rule list, which is NOT gated by condition — it applies to every condition that calls Node B, including Condition C (correction-only, which never touches Node A), and the same three rules were mirrored into `baseline.py`. This is exactly why Condition C's score moved (down, net −3) despite not using the rewritten Node A at all.

**Traced all 3 of Condition C's losses individually — worth noting for the thesis's limitations discussion:**
1. `california_schools` — the new column-ordering rule *did not reliably take effect*; same query, wrong column order anyway. Adding a prompt instruction doesn't guarantee compliance every time.
2. `thrombosis_prediction` (albumin question) — an otherwise near-identical query silently dropped a `LIMIT 1` clause between runs. A knock-on effect of the prompt changing elsewhere: at temperature=0, a *different* prompt (from the 3 new rules) deterministically produces a different completion, including in unrelated details.
3. `thrombosis_prediction` (PLT/Diagnosis) — the exact `Examination.Diagnosis` vs `Patient.Diagnosis` collision recurred, specifically because the duplicate-column-warning fix is gated behind `include_raw_fallback=True`, which Condition C deliberately sets `False` to keep its context equivalent to baseline's raw-schema view. **Condition C never receives that fix by design** — this is confirmation the fix works where applied, not evidence it failed.

**Synergy interpretation for the thesis narrative:** Context-only (B) alone nets only +1 — a small real effect. Full-agent (D) nets +5 — much larger than B or the correction loop (C, net −3) individually. This suggests the correction loop is fixing things that Node A's improved grounding sets up, which neither component achieves alone on this sample — context and correction appear complementary rather than independently additive here.