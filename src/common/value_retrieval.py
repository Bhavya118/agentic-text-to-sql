import json
import re
import difflib
from config import SEMANTIC_DIR

MIN_VALUE_LENGTH = 3
MIN_MATCH_RATIO  = 0.75
TOP_K_MATCHES    = 15


def _load_raw_profile(db_name: str) -> dict:
    profile_path = SEMANTIC_DIR / f"{db_name}_raw_profile.json"
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _candidate_values(profile: dict) -> list[tuple[str, str, str]]:
    """Flatten (table, column, value) triples from the profiler's sample values
    and top frequent values, deduplicated per column and filtered to values long
    enough to be meaningful entities (skips single characters/digits)."""
    candidates = []
    for table in profile["tables"]:
        table_name = table["table_name"]
        for col in table["columns"]:
            col_name = col["name"]
            seen = set()
            values = list(col.get("sample_values", []))
            values += [entry.get("value") for entry in col.get("value_distribution", [])]
            for v in values:
                sval = str(v).strip()
                if len(sval) >= MIN_VALUE_LENGTH and sval not in seen:
                    seen.add(sval)
                    candidates.append((table_name, col_name, sval))
    return candidates


def _question_ngrams(text: str, max_n: int = 3) -> list[str]:
    words = re.findall(r"[A-Za-z0-9']+", text)
    ngrams = []
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            ngram = " ".join(words[i:i + n])
            if len(ngram) >= MIN_VALUE_LENGTH:
                ngrams.append(ngram)
    return ngrams


def retrieve_matching_values(
    db_name: str,
    question: str,
    evidence: str = "",
    top_k: int = TOP_K_MATCHES,
    min_ratio: float = MIN_MATCH_RATIO
) -> list[dict]:
    """
    Fuzzy-matches entities mentioned in the question/evidence against real
    database values collected during profiling (schema_profiler.py). Grounds
    the SQL generator in the actual string casing/format stored in the
    database instead of letting it guess or paraphrase (e.g. matches 'SME'
    verbatim rather than expanding it to 'Small and Medium Enterprises').

    Pure string matching, no LLM call involved.
    """
    profile = _load_raw_profile(db_name)
    candidates = _candidate_values(profile)
    if not candidates:
        return []

    ngrams = _question_ngrams(f"{question} {evidence}")
    if not ngrams:
        return []

    best_per_key = {}
    for table_name, col_name, value in candidates:
        value_lower = value.lower()
        best_ratio = 0.0
        for ngram in ngrams:
            ngram_lower = ngram.lower()
            ratio = 1.0 if ngram_lower == value_lower else difflib.SequenceMatcher(
                None, ngram_lower, value_lower
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
        if best_ratio >= min_ratio:
            key = (table_name, col_name, value)
            if best_ratio > best_per_key.get(key, 0.0):
                best_per_key[key] = best_ratio

    ranked = sorted(best_per_key.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        {"table": t, "column": c, "value": v, "score": round(score, 2)}
        for (t, c, v), score in ranked
    ]


def format_value_matches(matches: list[dict]) -> str:
    """Render matched values as a prompt-ready block. Empty string if no matches."""
    if not matches:
        return ""
    lines = [f"  - {m['table']}.{m['column']} = '{m['value']}'" for m in matches]
    return (
        "Matched database values (these are real values found in the database — "
        "use them verbatim, with exact casing, in filter conditions where relevant):\n"
        + "\n".join(lines)
    )
