# Code Explanation — Your Thesis Codebase, and What Changed on 2026-07-30

This file is meant to be read start to finish. It explains how the codebase works today, then walks through everything that changed in tonight's session and *why* each change was made. `THESIS_MEETING_NOTES.md` has the detailed chronological log with exact evidence/citations if you need to dig deeper into any specific claim; this file is the "understand the whole picture" version.

---

## 1. What this project actually does

You're testing whether an LLM agent that (a) gets automatically-generated documentation about a database's schema, and (b) can retry and fix its own mistakes, writes better SQL than an LLM that just gets the question and the bare schema in one shot. You test this on BIRD, a benchmark of natural-language questions paired with "gold" (correct) SQL queries across 11 real-ish databases.

Three things get built and compared:
- **A one-shot baseline** — question + raw schema → SQL. No help, no retries.
- **An agentic system** — question + auto-generated schema documentation → SQL → run it → if it fails, diagnose and retry (up to 3 times).
- **An ablation study** — four versions of the pipeline that isolate exactly which piece (the documentation, or the retry loop, or both) is responsible for any difference in accuracy.

---

## 2. The three components, and how data flows between them

```
Component 1 (offline, run once per DB)
  .sqlite file → schema_profiler.py → *_raw_profile.json (types, PKs, FKs, sample values)
                                            ↓
                                    llm_synthesiser.py → *_semantic_context.json
                                    (plain-English descriptions, KPI flags, join paths)

Component 2 (runs once per question, per condition)
  question + evidence + *_semantic_context.json + *_raw_profile.json
      → [Node A: pick relevant schema] → [Node B: write SQL] → [Node C: execute]
                                                  ↑                    ↓ (on failure)
                                                  └──── [Node D: diagnose + fix] ←┘

Component 3 (the harness that runs everything and scores it)
  dev.json (questions + gold SQL) → harness.py → runs baseline.py AND the 4 agent conditions
      → ex_checker.py compares each predicted SQL's result against gold SQL's result
      → checkpoints saved after every question → aggregate_results.json at the end
```

The key thing to internalize: **`*_raw_profile.json` and `*_semantic_context.json` are two separate files with different information**, and a recurring theme in tonight's fixes is that the code wasn't using both of them together properly.

- `raw_profile.json` has: table names, column names, **data types**, **primary key flags**, foreign keys, and **actual sample values** pulled straight from the database.
- `semantic_context.json` has: LLM-written plain-English descriptions, KPI flags, notes, join paths. It does **not** carry types, PK flags, or sample values — the synthesiser only glances at 3 sample values per column to help it write the description, then throws that information away.

Tonight's biggest fixes are all variations on "merge these two files properly at the point where the LLM needs to see the schema," because before tonight, downstream code was only using one or the other, never both.

---

## 3. The agent's four nodes, as they exist right now

All of this lives in `src/agent/nodes.py`.

### Node A — `node_context_retrieval` (schema linking / "what do I need to look at?")

**What it does today (after tonight's rewrite):** it shows the LLM the *entire* schema — every table, every column, with type, PK flag, description, KPI flag, sample values, all merged from both JSON files — plus two new things:
1. A list of real database values that fuzzy-match words in the question (e.g. if the question says "Fresno county," it'll show you that `schools.County = 'Fresno'` is a real value in the database, so the model uses the exact right string instead of guessing).
2. A warning about column names that exist identically on more than one table (e.g. both `Patient` and `Examination` in one database have a column called `Diagnosis` — that's a real trap, not a hallucination, and the model needs to be told explicitly to pick the right one).

Then — and this is the important architectural change — **the LLM is not allowed to write a paragraph back.** It must respond with strict JSON:
```json
{
  "tables": {
    "Patient": ["ID", "Diagnosis"],
    "Laboratory": ["ID", "PLT"]
  },
  "join_notes": "Patient.ID = Laboratory.ID"
}
```
Python then takes that JSON, looks up each named table/column against the *real* schema, and builds the actual text block Node B will see — filling in type/description/samples from the two JSON files itself. If the LLM named a table or column that doesn't exist, it's silently dropped, not rendered. If the LLM's JSON is malformed entirely, there's a fallback message and Node B's own raw-schema safety net (below) picks up the slack.

**Why it changed:** before tonight, Node A wrote a free-text paragraph describing what it thought was relevant. Free text is exactly where an LLM has room to be "helpful" — inventing a plausible-sounding join, or describing a wrong-but-real column as if it were the obvious choice. Every top-performing system in the published literature (CHESS, XiYan-SQL, E-SQL) does the structured-output version instead — the model's only degree of freedom is picking real identifiers off an enumerated list, not writing persuasive prose.

### Condition C's entry point — `node_raw_schema_context`

This isn't Node A — it's a stand-in used only by ablation Condition C. It skips schema linking entirely and just hands Node B the same bare schema the baseline sees (table + column names + types, nothing else). This exists purely so we can measure "what does the self-correction loop add, with zero help from the documentation layer?"

### Node B — `node_sql_generator` ("write the actual SQL")

Gets: the question, evidence (verbatim — never let Node A paraphrase it), Node A's rendered selection (or Condition C's raw schema), and — **only when `include_raw_fallback` is True** (true for Conditions B and D, false for Condition C) — three extra safety nets:
1. The full raw schema, "in case Node A missed something."
2. The same fuzzy-matched real values shown to Node A.
3. The same duplicate-column-name warning shown to Node A.

Why the gating? Condition C is supposed to mirror baseline's context level (just the bare schema) so it cleanly isolates the correction loop's contribution. If Condition C got the extra enrichments too, it wouldn't be a clean "correction only" comparison anymore.

Node B's rules (the numbered list right before it asks for SQL) got three new additions tonight:
- Prefer `RANK()` over `ROW_NUMBER()` when the question implies ranking — they're NOT interchangeable, `RANK()` handles ties the way BIRD's gold answers expect and `ROW_NUMBER()` doesn't.
- Order SELECT columns to match the order things are mentioned in the question — because BIRD's grading script cares about column order within a row (see section 6).
- Don't add a JOIN or table that isn't strictly necessary — a direct instruction against the "plausible-but-wrong alternative" tendency.

`temperature=0` was also added (was previously unset, meaning non-deterministic default behavior) — for a task like SQL generation, determinism is usually preferable.

### Node C — `node_executor` ("run it and see")

Unchanged tonight. Executes the SQL against DuckDB. Success → done. Failure → logs the error message and moves to Node D.

### Node D — `node_critic` ("diagnose and suggest a fix")

Classifies the error (SYNTAX / SEMANTIC / LOGIC) and writes a correction instruction, then routes back to Node B. New tonight: **before** the LLM call, plain Python code parses the error message for a "column not found" pattern, and if it finds one, looks up the *real* schema to say exactly which table the column actually lives on. This costs zero extra API calls and means the critic gets ground truth instead of having to correctly parse a DuckDB error string on its own.

**Important limitation, unchanged by anything tonight:** Node D only ever fires when `execution_error` is set — i.e. when the SQL crashes. A query that runs cleanly but returns the *wrong answer* never reaches Node D at all. This turns out to be a big deal (see section 7).

---

## 4. The four ablation conditions

`src/agent/graph.py` builds three separate LangGraph state machines (plus `baseline.py` is the fourth, simpler condition that isn't a graph at all):

| | Node A (schema linking) | Node D (self-correction) | Purpose |
|---|---|---|---|
| **A — Baseline** | No | No | The "no help at all" control |
| **B — Context only** | Yes | No | Isolates: does the documentation layer alone help? |
| **C — Correction only** | No (raw schema instead) | Yes | Isolates: does retry-on-failure alone help? |
| **D — Full agent** | Yes | Yes | The complete system — "the agent" in casual conversation |

`harness.py` builds all three graphs once per database, then runs every one of the 55 test questions through baseline + all three agent conditions, checkpointing after each question so a crash doesn't lose progress. `ex_checker.py` compares each predicted SQL's *result* (not its text) against gold SQL's result to decide correct/incorrect.

---

## 5. The new utility files

### `src/common/schema_utils.py`
Pure Python, zero LLM calls, all built or extended tonight:
- `get_raw_schema(db_path)` — bare table/column list (existed before, moved here so `baseline.py` and `nodes.py` share one copy instead of two).
- `find_columns(db_path, column_name)` — "which real tables actually have a column called X?" Used by Node D.
- `extract_missing_columns(error_msg)` — pulls a column name out of a DuckDB "column not found"-style error message.
- `find_duplicate_columns(db_path)` — the collision detector. Scans every table, finds column names that appear on 2+ tables, and deliberately *excludes* primary keys and columns that are part of a declared foreign key relationship (those repeat by design — e.g. `raceId` legitimately appears on 5 different `formula_1` tables because they all reference races — that's normal, not a trap).

### `src/common/value_retrieval.py`
Also pure Python (uses the standard library's `difflib` for fuzzy string matching, no embeddings, no extra dependency):
- `retrieve_matching_values(db_name, question, evidence)` — breaks the question into overlapping word groups (1-3 words at a time), and fuzzy-matches them against the actual sample values collected during profiling. If "Fresno" is mentioned and "Fresno" is a real value in `schools.County`, this surfaces that pairing.
- This exists because `schema_profiler.py` was already collecting exactly this data (`sample_values`, `value_distribution`) and nothing downstream was using it — a classic case of data being collected but never consumed.

---

## 6. Two benchmark quirks worth understanding (not bugs you introduced)

**BIRD's grading cares about column order.** If gold SQL selects `(City, Grade, School)` and your query selects `(City, School, Grade)` — same information, different order — BIRD scores it as wrong. This is confirmed as BIRD's actual official behavior, not a flaw in `ex_checker.py`. It's why the "order SELECT columns like the question mentions them" rule was added.

**DuckDB's `REAL` type is 32-bit, not 64-bit.** If gold SQL writes `CAST(x AS REAL)`, that truncates precision. A generated query using `x * 1.0` instead (mathematically equivalent, full double precision) can produce a *more accurate* number that still fails the exact-match comparison because it doesn't bit-for-bit equal the deliberately-truncated gold value. This actually happened during tonight's testing (confirmed by directly executing both versions) and explains one of the "regressions" — it wasn't a logic error, it was more precision than the benchmark wanted.

---

## 7. Why the agent was losing to baseline, and what actually fixed it

This is the throughline of tonight's whole session, so it's worth having in one place:

1. **First hypothesis (partially right):** Node B only ever saw Node A's summary, never the raw schema — if Node A dropped something, Node B had no way to recover it. **Fix:** raw-schema safety net added to Node B. This helped, but didn't fully explain the underperformance.

2. **Second, sharper finding:** Node A wasn't just *dropping* information — it was actively pointing Node B at a **real but wrong** column, specifically when the same column name existed on two different tables (`Patient.Diagnosis` vs `Examination.Diagnosis` — both genuinely exist). This is a name collision, not a hallucination, and it's invisible to Node D because the resulting query executes just fine, it just answers a subtly different question. **Fix:** duplicate-column detector + explicit warning.

3. **Third finding, the broadest one:** even beyond exact-name collisions, Node A would suggest a denormalized-but-differently-named column, or an unnecessarily complicated join, when a simpler and correct path existed. Research into how top BIRD-leaderboard systems (CHESS, XiYan-SQL, RSL-SQL) avoid this pointed to one dominant pattern: **stop letting the schema-linking step write free text.** Force it to output a strict, checkable list of real identifiers instead. **Fix:** the Node A structural rewrite described in section 3.

4. **A separate, structural limitation that's still open:** Node D (the self-correction loop) only fires on queries that *crash*. Research (the ErrorLLM paper, cited in the meeting notes) found that in real measurements, only about 3% of incorrect SQL queries actually throw an execution error — the rest run cleanly and are just wrong. That means the correction loop, as designed, can only ever catch a small slice of the mistakes the system makes. This wasn't fixed tonight (the real fixes — a second verification pass, or generating multiple candidates and voting — both cost extra API calls per question) but it's the most important thing to understand about *why* self-correction alone (Condition C) doesn't reliably beat baseline on its own.

**Net result after all of tonight's fixes:** on the 55-question sample, the full agent (Condition D) went from performing *worse* than baseline (−5.45 percentage points) to performing clearly better (+7.27 percentage points), with zero individual questions regressing between the two runs — the cleanest result of the whole session. Context-only and correction-only alone are still roughly tied with baseline on this small sample; the improvement shows up specifically when both pieces work together. Full numbers, per-question SQL diffs, and the exact reasoning behind each traced regression are in `THESIS_MEETING_NOTES.md` under the 2026-07-30 entries.

---

## 8. If you want to verify any of this yourself tonight

Everything above was checked without spending any money — no OpenAI API calls. You can do the same:
```powershell
venv\Scripts\activate
python -c "from src.common.value_retrieval import retrieve_matching_values; print(retrieve_matching_values('california_schools', 'schools in Fresno county', ''))"
python -c "from src.common.schema_utils import find_duplicate_columns; from pathlib import Path; print(find_duplicate_columns(Path('data/bird/dev_databases/thrombosis_prediction/thrombosis_prediction.sqlite')))"
```
Both run instantly, read only local files, and will show you exactly what Node A/B see before any LLM is involved.
