"""Central configuration constants for Boulder Scroll.

Single source of truth for values that were previously duplicated across
``app.py``, ``run.py`` and ``src/pipeline.py``. The values here are identical to
the originals — this module only removes the duplication, it does not change any
behaviour.
"""

# --- Output video geometry (portrait 9:16) ---
OUT_W = 540
OUT_H = 960

# --- Reframing defaults ---
SMOOTHING_ALPHA = 0.1   # EMA factor: 0.1 = very smooth/slow, 0.4 = reactive
PERSON_FILL = 0.65      # person fills this fraction of frame height (0.5–0.85)

# --- Overlay ---
TRAIL_LEN = 40          # frames of CoM history to show in the skeleton trail

# --- Web server runtime directories (created on startup) ---
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"

# --- /render form defaults (web) ---
DEFAULT_ALPHA = SMOOTHING_ALPHA
DEFAULT_FILL = PERSON_FILL
