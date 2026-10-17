"""P0-2 integrity guard: no fabricated metrics may live in source.

Every number shown in the UI, API responses or benchmark scripts must come from
code that ran. This test scans backend/ and frontend/src (excluding tests and
data) for the literal patterns of past fabrications. If it fails, replace the
literal with a measured value or an honest empty state -- do not adjust this
test to hide a fake number.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
SCAN_DIRS = [REPO / "backend", REPO / "frontend" / "src"]
EXTRA_FILES = [REPO / "run_bench.py"]
SKIP_DIRS = {"tests", "__pycache__", "data", "node_modules", "dist"}

# Literal fragments of past fabrications (S0-1..S0-5).
LITERAL_PATTERNS = [
    r"(?<![\d.])0\.85(?![\d])",          # int(N * 0.85) fake greedy moves
    r"(?<![\d.])0\.42(?![\d])",          # int(N * 0.42) fake greedy moves
    r"\*\s*4\s*\+\s*15",                 # max(real, 4*ours+15) fake scratch floor
    r"(?<![\d.])38\.2(?![\d])",          # typed-in "10,000 signals in 38.2 s"
    r"1\.00x",                           # hard-coded efficiency verdict
    r":\s*(26|221)(?=[,\}\s\)])",        # revision fallback literals
]

# Non-zero numeric literals assigned to metric keys, e.g. `violations: 142`,
# `rev_b_moves = 850`, `"runtime_s": 1.62`. Zero defaults (pydantic `= 0`)
# are allowed; anything asserted as a measurement must be computed.
METRIC_KEY_PATTERN = re.compile(
    r"['\"]?\b(violations|moves|rev_b_moves|moves_ours|moves_from_scratch"
    r"|runtime_s|runtime|cabinets|cabinets_used)\b['\"]?\s*[:=]\s*(-?\d+\.?\d*)"
)


def _iter_source_files():
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.suffix not in {".py", ".ts", ".tsx"}:
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(REPO).parts):
                continue
            yield p
    for f in EXTRA_FILES:
        if f.exists():
            yield f


def test_no_fabricated_literals_in_source():
    hits = []
    compiled = [re.compile(p) for p in LITERAL_PATTERNS]
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(REPO)
        for i, line in enumerate(text.splitlines(), 1):
            for rx in compiled:
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()}")
    assert not hits, (
        "Fabricated metric literals found in source (see P0-1). "
        "Measure the value or show an empty state instead:\n" + "\n".join(hits)
    )


def test_no_hardcoded_metric_values():
    hits = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(REPO)
        for i, line in enumerate(text.splitlines(), 1):
            m = METRIC_KEY_PATTERN.search(line)
            if m and float(m.group(2)) != 0.0:
                hits.append(f"{rel}:{i}: {line.strip()}")
    assert not hits, (
        "Hard-coded metric values found in source. "
        "Every metric must be computed by running code:\n" + "\n".join(hits)
    )
