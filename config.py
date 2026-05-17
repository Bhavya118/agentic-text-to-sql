import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR     = Path(__file__).parent
DATA_DIR     = ROOT_DIR / "data" / "bird"
OUTPUTS_DIR  = ROOT_DIR / "outputs"
SEMANTIC_DIR = OUTPUTS_DIR / "semantic_context"
RESULTS_DIR  = OUTPUTS_DIR / "results"

# ── API ───────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL      = os.getenv("LLM_MODEL", "gemini-2.5-flash")

# ── Profiler settings ─────────────────────────────────────────────────────────
MAX_SAMPLE_ROWS = 5
MAX_FREQ_VALUES = 10

# ── Agent settings ────────────────────────────────────────────────────────────
MAX_CORRECTIONS = 3

# ── Evaluation settings ───────────────────────────────────────────────────────
BASELINE_MODEL = LLM_MODEL