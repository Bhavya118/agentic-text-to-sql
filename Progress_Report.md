# Progress Report — Ablation Study and Schema-Linking Improvements

## 1. Where this round of work started

The 4-condition ablation study requested in the last supervision meeting — isolating the contribution of (a) automated semantic context and (b) the self-correcting execution loop — had not yet been built. Only the baseline (Condition A) and the full agent (Condition D) existed. Evidence hints had already been added to both baseline and agent for a fair comparison, and a data integrity issue in the `european_football_2` database (48 of 129 gold queries referencing a column that didn't exist on the table they claimed to) had been found and patched.

Two things were still open going into this round:
- The ablation study itself (Conditions B and C).
- An explanation for why, on informal spot checks, the full agent wasn't clearly beating the baseline.

## 2. Building the ablation framework

Implemented the two missing conditions:
- **Condition B (context only):** semantic context retrieval, no self-correction. *(`src/agent/graph.py`)*
- **Condition C (correction only):** the self-correction loop, but fed the same raw schema the baseline sees, with no semantic context layer. *(`src/agent/graph.py`)*

All four conditions are scored per question and checkpointed by the evaluation harness. *(`src/evaluator/harness.py`)*

While wiring this up, a structural gap became apparent: the SQL-generation step only ever saw the *summarized* output of the context-retrieval step — if that summary dropped a table or column the query needed, there was no way to recover it, whereas the baseline always sees the complete, unfiltered schema. Added a raw-schema fallback so the generator always has the full schema available as a safety net, regardless of what the retrieval step chose to summarize. *(`src/agent/nodes.py`)* Also fixed `temperature` being left unset (defaulting to non-deterministic output) — set to 0 for a task where consistency should help. *(`src/agent/nodes.py`, `src/evaluator/baseline.py`)*

## 3. First ablation run

| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 58.18% | — |
| B — Context only | 52.73% | −5.45pp |
| C — Correction only | 60.0% | +1.82pp |
| D — Full agent | 52.73% | −5.45pp |

**Observation:** self-correction alone provided a small genuine improvement. Adding the semantic context layer, on its own or combined with correction, *hurt* accuracy. This was the opposite of the expected direction and needed explaining before any further tuning would be meaningful.

## 4. Investigating the regression

Traced the specific questions where context-aware conditions performed worse than baseline. The clearest example, in the `thrombosis_prediction` database:

> *"Please list a patient's platelet level if it is within the normal range and if he or she is diagnosed with MCTD."*

Baseline correctly filtered on `Patient.Diagnosis = 'MCTD'`. The context-aware conditions instead used `Examination.Diagnosis = 'MCTD'`. Checking the actual schema confirmed both columns genuinely exist — `Diagnosis` is defined independently on both the `Patient` and `Examination` tables. This isn't a hallucinated column; it's a real name collision, and the context-retrieval step was silently picking the wrong one of two valid options.

**Fix:** automatic detection of column names that appear identically on more than one table, deliberately excluding primary keys and columns that participate in a declared foreign key relationship (those repeat by design — e.g. a `raceId` column legitimately appears on five different tables in one database purely because they all reference the same parent table). *(`src/common/schema_utils.py`)* The remaining genuine collisions are surfaced as an explicit disambiguation warning to both the schema-linking and SQL-generation steps. *(`src/agent/nodes.py`)*

## 5. Literature review — how do stronger systems handle this?

Reviewed recent published systems evaluated on the same benchmark (CHASE-SQL, XiYan-SQL, DIN-SQL, DAIL-SQL, CHESS, MCS-SQL) for techniques applicable to this architecture. Two findings stood out:

- **Value grounding:** several systems (CHESS, XiYan-SQL) fuzzy-match entities mentioned in the question against real values stored in the database, so the model uses the exact string a filter needs rather than guessing a plausible variant. The schema profiler already collected exactly this data (sample values, value distributions per column) — it just wasn't being used downstream. Wired it in. *(new module: `src/common/value_retrieval.py`, called from `src/agent/nodes.py`)*
- **Schema representation:** XiYan-SQL reports a measurable accuracy gain from representing each column as a structured tuple (name, type, primary-key flag, description, example values) rather than prose. Adopted the same format. *(`src/agent/nodes.py`)*
- A separate, more specific finding from recent work on SQL self-correction: only a small fraction of incorrect SQL queries actually raise an execution error — most run cleanly and simply return the wrong answer. Since the correction loop can only react to queries that error out, this places a structural ceiling on what self-correction alone can catch, independent of anything else in the pipeline.

## 6. Systematic audit of remaining errors

Rather than continue spot-checking, audited every question (across all 11 databases) where the baseline answered correctly but a context-aware condition did not — 6 of 55. Categorising each:

| Cause | Count |
|---|---|
| Column name collision across tables (as in section 4) | 1 |
| Grading-methodology sensitivity to SELECT column order, not a reasoning error | 1 |
| Prompt ambiguity: `RANK()` vs `ROW_NUMBER()` treated as interchangeable when they aren't | 1 |
| Model choosing a plausible-but-incorrect alternative — different naming, not a collision | 3 |

The duplicate-column fix from section 4 addressed exactly one of the six. Two more turned out to be separate, easily-fixed issues: the ranking-function ambiguity (tightened the instruction to prefer `RANK()`, which handles tied values the way the gold queries expect), and column ordering (BIRD's grading compares results as exact row tuples, so column order within a row matters — added an instruction to order SELECT columns the way the question mentions them). Both fixes applied to the agent's SQL-generation prompt and the baseline's prompt identically, to keep the comparison fair. *(`src/agent/nodes.py`, `src/evaluator/baseline.py`)* The remaining three confirmed a broader pattern: the model choosing a denormalized-but-differently-named column, or an unnecessarily complex join, when a simpler and correct option existed.

## 7. A structural fix for schema linking

That broader pattern — "plausible but wrong" schema choices — is a documented problem in the text-to-SQL literature (schema-linking over-inclusion). Reviewing how the stronger systems avoid it (CHESS, RSL-SQL, E-SQL) pointed to a consistent pattern: none of them let the schema-linking step write free-text descriptions. Free text is exactly where a model has room to describe an incorrect join as if it were the obvious choice.

Redesigned the context-retrieval step accordingly: it now must respond with a strict, validated list of real table and column names (not prose), and the actual schema description shown to the SQL generator is then assembled deterministically in code from that list — any table or column name that doesn't actually exist in the schema is dropped rather than rendered. *(`src/agent/nodes.py`)* The prompt was also reframed from "select relevant elements" to "select the minimal sufficient set, and justify each one against the literal question text," and an explicit instruction against unnecessary joins was added to both the agent and baseline prompts, consistent with the general finding that naming a model's known biases explicitly (rather than generic caution) measurably improves compliance. *(`src/agent/nodes.py`, `src/evaluator/baseline.py`)*

Two further techniques from the same review — verifying each schema selection against the question in a second pass, and generating multiple independent candidate selections and keeping only the ones that agree — were identified as promising but require an additional model call per question. Deferred pending a cost/benefit decision, rather than adding an unvalidated additional step immediately before a scheduled evaluation run.

## 8. Second ablation run

| Condition | EX | vs Baseline |
|---|---|---|
| A — Baseline | 54.55% | — |
| B — Context only | 54.55% | +0.00pp |
| C — Correction only | 54.55% | +0.00pp |
| D — Full agent | **61.82%** | **+7.27pp** |

The full agent moved from underperforming the baseline by 5.45 points to outperforming it by 7.27 points. Cross-checked this wasn't a fluke: comparing individual questions between the two runs, the full agent gained 5 questions and lost none — the cleanest result across either run. One concrete example, from `debit_card_specializing`: the baseline guessed a currency filter as `Currency = 'euro'`; the agent correctly used `'EUR'`, the real value stored in the database — a direct, attributable win from the value-grounding fix in section 5.

## 9. Why context-only and correction-only appear unchanged — verifying it wasn't a measurement error

Conditions A, B, and C all landed at the identical 54.55% in the second run. Before treating that as meaningful, checked whether it reflected a real absence of change or a coincidence. Breaking down per-database results showed each condition's results differed substantially database-by-database — the equal *totals* were not equal *behaviour*. Quantifying the actual question-level movement between the two runs confirmed this:

| Condition | Gained | Lost | Net |
|---|---|---|---|
| A — Baseline | 1 | 3 | −2 |
| B — Context only | 2 | 1 | +1 |
| C — Correction only | 0 | 3 | −3 |
| D — Full agent | 5 | 0 | **+5** |

Each condition moved independently; the equal final totals for A, B, and C were coincidental on this sample size, not evidence that nothing changed.

This also raised a fair question: Condition C doesn't use the redesigned schema-linking step at all, so why did its score move (down) at the same time? The answer is that the ranking-function and column-ordering fixes from section 6 live in the SQL-generation step itself, which every condition uses — including Condition C — so those instructions affected all conditions, not only the ones using the new schema-linking design. Tracing Condition C's three lost questions individually showed three distinct, unrelated causes: one where the column-ordering instruction simply wasn't followed on that attempt; one where an unrelated part of the query changed as a side effect of the prompt being edited elsewhere (a reminder that even small prompt changes can have effects beyond their intended target); and one recurrence of the exact column-collision problem from section 4 — which Condition C is, by design, not given the fix for, since it's meant to mirror the baseline's schema exposure level for a clean comparison. That recurrence is a confirmation the fix works where it's applied, not a failure of it.

**Interpretation:** context alone contributes a small net improvement (+1); correction alone, on this sample, net loses ground (−3) once the same-generation-step fixes are accounted for; but combined, the full agent nets +5 — noticeably larger than either component individually. This suggests the two mechanisms are complementary rather than simply additive: the correction loop appears to be fixing cases that only arise once the context layer has already improved the starting point.

## 10. Two grading-methodology findings worth noting separately

Two issues surfaced during the investigation that are properties of the benchmark and execution engine, not defects in the system being evaluated:

- **Column order sensitivity.** The benchmark's execution-accuracy metric compares result rows as ordered tuples — a query returning the same information in a different column order scores as incorrect. Confirmed this matches the benchmark's own official grading behaviour, not an artifact of the evaluation code used here. *(comparison logic: `src/evaluator/ex_checker.py`)*
- **Floating-point precision in the execution engine.** The execution engine's `REAL` type is 32-bit, not the standard 64-bit double. A gold query using `CAST(x AS REAL)` truncates precision; a generated query computing the same value with full double precision can produce a numerically *more* accurate answer that still fails an exact-match comparison against the deliberately-truncated gold value. Verified this directly by executing both variants and comparing outputs bit-for-bit.

Both are worth a line in the thesis's discussion of the benchmark's grading methodology.

## 11. Current state and next steps

- Ablation framework complete and run twice, with the second run showing a clear, individually-verified improvement for the full agent and no regressions.
- Open items: a final run on the full 1,534-question set rather than the 55-question development sample (see section 12 for why this matters); few-shot example retrieval (needs a held-out training split, distinct from the evaluation set, to avoid undermining the system's cold-start design goal); and the two deferred schema-linking techniques from section 7 (verification pass, multi-candidate voting), both of which trade additional inference cost for a further reduction in the "plausible but wrong" failure mode.

## 12. Is the 55-question result strong enough to claim an improvement?

Before treating the second run's +7.27pp gap as a result, checked whether it holds up statistically. Since baseline and the full agent are scored on the *same* 55 questions, the appropriate test is McNemar's test on paired outcomes, not a comparison of two independent samples.

| | Agent correct | Agent wrong |
|---|---|---|
| **Baseline correct** | 27 | 3 |
| **Baseline wrong** | 7 | 18 |

Only the two disagreement cells matter for significance: the agent wins 7 of the 10 questions where the two conditions disagree, baseline wins 3. Running the exact McNemar test on that 7-vs-3 split gives **p = 0.34** — well short of the conventional 0.05 threshold. With only 10 discordant pairs, even a fairly lopsided-looking split isn't enough; something closer to 9-vs-1 would be needed to reach significance at this sample size.

**Conclusion:** the 55-question result is a genuine, mechanistically-explained, directionally positive pilot finding — not yet a statistically defensible claim that the full agent outperforms the baseline. That distinction matters and shouldn't be glossed over. The 55-question sample was always intended as a fast, low-cost way to iterate and debug (each full run costs real money and meaningful time) before committing to the full 1,534-question evaluation, which has roughly 28× the statistical power and is the run this claim will actually stand or fall on.
