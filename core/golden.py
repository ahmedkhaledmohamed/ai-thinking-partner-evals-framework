"""
Golden file management — save, load, compare, and audit golden baselines.

Golden files live at ``~/.ai-evals/golden/{category}/{name}.golden.json``
by default.  The comparison logic ports Nestor's topic-overlap and
severity model while adding dict-level structural diffing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import load_config

_DEFAULT_GOLDEN_DIR = "~/.ai-evals/golden"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GoldenComparison:
    golden_path: str
    match: bool
    severity: str  # "none", "minor", "major", "improved"
    topic_overlap: float  # 0.0–1.0
    missing_topics: list[str] = field(default_factory=list)
    new_topics: list[str] = field(default_factory=list)
    golden_age_days: int = 0
    summary: str = ""
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "golden_path": self.golden_path,
            "match": self.match,
            "severity": self.severity,
            "topic_overlap": round(self.topic_overlap, 3),
            "missing_topics": self.missing_topics,
            "new_topics": self.new_topics,
            "golden_age_days": self.golden_age_days,
            "summary": self.summary,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _golden_dir(golden_dir: str | None = None) -> Path:
    """Resolve the golden directory, falling back to config then default."""
    if golden_dir:
        return Path(golden_dir).expanduser()
    try:
        config = load_config()
        return Path(config.get("golden_dir", _DEFAULT_GOLDEN_DIR)).expanduser()
    except Exception:
        return Path(_DEFAULT_GOLDEN_DIR).expanduser()


def _golden_path(category: str, name: str, golden_dir: str | None = None) -> Path:
    return _golden_dir(golden_dir) / category / f"{name}.golden.json"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def load_golden(category: str, name: str, golden_dir: str | None = None) -> dict | None:
    """Load a golden file.  Returns None if it doesn't exist."""
    path = _golden_path(category, name, golden_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_golden(category: str, name: str, data: dict | list, golden_dir: str | None = None) -> Path:
    """Save (or overwrite) a golden file.  Returns the written path."""
    path = _golden_path(category, name, golden_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        "meta": {
            "category": category,
            "name": name,
            "created": datetime.now(timezone.utc).isoformat(),
        },
        "data": data,
    }

    path.write_text(json.dumps(envelope, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def list_golden_files(golden_dir: str | None = None) -> list[dict]:
    """List all golden files with metadata.

    Returns a list of dicts with keys: category, name, path, age_days, size_bytes.
    """
    base = _golden_dir(golden_dir)
    if not base.is_dir():
        return []

    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for path in sorted(base.rglob("*.golden.json")):
        rel = path.relative_to(base)
        parts = rel.parts  # e.g. ("pipeline", "product-catalog.golden.json")
        category = parts[0] if len(parts) > 1 else "uncategorised"
        name = path.stem.replace(".golden", "")

        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_days = (now - mtime).days

        results.append({
            "category": category,
            "name": name,
            "path": str(path),
            "age_days": age_days,
            "size_bytes": path.stat().st_size,
        })

    return results


def check_golden_staleness(golden_dir: str | None = None, max_days: int = 30) -> list[dict]:
    """Return golden files older than *max_days*."""
    return [g for g in list_golden_files(golden_dir) if g["age_days"] > max_days]


# ---------------------------------------------------------------------------
# Topic extraction  (ported from Nestor's eval_runner._extract_topics)
# ---------------------------------------------------------------------------

# Domain terms relevant to Ahmed's messaging ecosystem.  These are checked
# case-insensitively against the text to augment the regex-based extraction.
_DOMAIN_TERMS = [
    "pendragon", "goodfeathers", "raven", "fiona", "tron", "pushka",
    "goose", "longclaw", "gabito", "mastermyr",
    "bigtable", "pubsub", "grpc", "protobuf",
    "push", "inbox", "in-app", "opt-in", "opt-out",
    "frequency", "capping", "delivery", "reachability",
    "moments", "orchestration", "campaign",
    "mau", "conversion", "retention", "churn",
    "experiment", "a/b test", "treatment", "control",
]


def _extract_topics(text: str) -> set[str]:
    """Extract key topics from free-form text for overlap comparison.

    Extracts:
    - Acronyms (2+ uppercase letters)
    - CamelCase identifiers
    - Known domain terms
    """
    topics: set[str] = set()

    # Acronyms (2+ uppercase letters, optionally followed by lowercase)
    for m in re.findall(r"\b[A-Z]{2,}[a-z]*\b", text):
        topics.add(m.lower())

    # CamelCase terms
    for m in re.findall(r"\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b", text):
        topics.add(m.lower())

    # Domain terms (case-insensitive substring match)
    text_lower = text.lower()
    for term in _DOMAIN_TERMS:
        if term in text_lower:
            topics.add(term)

    return topics


# ---------------------------------------------------------------------------
# Comparison engine
# ---------------------------------------------------------------------------


def _compare_text_golden(
    actual_text: str,
    golden_text: str,
    expected_mentions: list[str] | None = None,
) -> GoldenComparison:
    """Compare two free-text outputs (e.g. research reports) using topic overlap."""
    new_topics = _extract_topics(actual_text)
    golden_topics = _extract_topics(golden_text)

    # Overlap: fraction of golden topics present in new
    if golden_topics:
        overlap_count = len(new_topics & golden_topics)
        topic_overlap = overlap_count / len(golden_topics)
    else:
        topic_overlap = 1.0

    new_only = sorted(new_topics - golden_topics)
    golden_only = sorted(golden_topics - new_topics)

    details: list[str] = []
    missing_mentions: list[str] = []

    if new_only:
        details.append(f"New topics (potential improvement): {new_only[:10]}")
    if golden_only:
        details.append(f"Topics in golden missing from actual: {golden_only[:10]}")

    # Check expected mentions
    if expected_mentions:
        actual_lower = actual_text.lower()
        missing_mentions = [m for m in expected_mentions if m.lower() not in actual_lower]
        if missing_mentions:
            details.append(f"Missing expected mentions: {missing_mentions}")

    # Determine severity
    improvement_ratio = len(new_topics) / len(golden_topics) if golden_topics else 1.0

    if topic_overlap < 0.25:
        severity = "major"
        match = False
    elif improvement_ratio > 1.2 and topic_overlap >= 0.5:
        severity = "improved"
        match = True
        details.insert(0, f"Improvement: new has {improvement_ratio:.0%} of golden's topic count")
    elif topic_overlap < 0.7 or missing_mentions:
        severity = "minor"
        match = False
    else:
        severity = "none"
        match = True

    return GoldenComparison(
        golden_path="(text comparison)",
        match=match,
        severity=severity,
        topic_overlap=topic_overlap,
        missing_topics=missing_mentions or golden_only[:10],
        new_topics=new_only[:10],
        golden_age_days=0,
        summary="; ".join(details) if details else "All checks passed",
        details=details,
    )


def _compare_dict_golden(
    actual: dict,
    golden: dict,
    expected_keys: list[str] | None = None,
) -> GoldenComparison:
    """Compare two dict-shaped outputs structurally."""
    details: list[str] = []
    all_ok = True

    actual_keys = set(actual.keys())
    golden_keys = set(golden.keys())

    missing_keys = golden_keys - actual_keys
    new_keys = actual_keys - golden_keys

    if missing_keys:
        details.append(f"Keys missing from actual: {sorted(missing_keys)}")
        all_ok = False
    if new_keys:
        details.append(f"New keys in actual: {sorted(new_keys)}")

    # Check expected keys
    if expected_keys:
        absent = [k for k in expected_keys if k not in actual]
        if absent:
            details.append(f"Expected keys absent: {absent}")
            all_ok = False

    # Type-level comparison for shared keys
    type_mismatches: list[str] = []
    length_diffs: list[str] = []

    for key in golden_keys & actual_keys:
        g_val = golden[key]
        a_val = actual[key]

        if type(g_val) != type(a_val):
            type_mismatches.append(f"{key}: golden={type(g_val).__name__}, actual={type(a_val).__name__}")

        # List length comparison
        if isinstance(g_val, list) and isinstance(a_val, list):
            if len(g_val) > 0 and len(a_val) == 0:
                length_diffs.append(f"{key}: golden has {len(g_val)} items, actual has 0")
                all_ok = False
            elif len(g_val) > 0:
                ratio = len(a_val) / len(g_val)
                if ratio < 0.5 or ratio > 2.0:
                    length_diffs.append(
                        f"{key}: length changed significantly ({len(g_val)} -> {len(a_val)})"
                    )

    if type_mismatches:
        details.append(f"Type mismatches: {type_mismatches}")
        all_ok = False
    if length_diffs:
        details.append(f"Length changes: {length_diffs}")

    # Key overlap as topic_overlap proxy
    if golden_keys:
        overlap = len(actual_keys & golden_keys) / len(golden_keys)
    else:
        overlap = 1.0

    # Severity
    if not all_ok and overlap < 0.5:
        severity = "major"
    elif not all_ok:
        severity = "minor"
    elif new_keys and not missing_keys:
        severity = "improved"
    else:
        severity = "none"

    return GoldenComparison(
        golden_path="(dict comparison)",
        match=all_ok or severity == "improved",
        severity=severity,
        topic_overlap=overlap,
        missing_topics=sorted(missing_keys),
        new_topics=sorted(new_keys),
        golden_age_days=0,
        summary="; ".join(details) if details else "All checks passed",
        details=details,
    )


def _compare_list_golden(
    actual: list,
    golden: list,
) -> GoldenComparison:
    """Compare two list-shaped outputs (length, element-type consistency)."""
    details: list[str] = []
    all_ok = True

    g_len = len(golden)
    a_len = len(actual)

    if g_len > 0 and a_len == 0:
        details.append(f"Actual is empty (golden has {g_len} items)")
        all_ok = False
    elif g_len > 0:
        ratio = a_len / g_len
        if ratio < 0.5:
            details.append(f"Significant shrinkage: {g_len} -> {a_len} items")
            all_ok = False
        elif ratio > 2.0:
            details.append(f"Significant growth: {g_len} -> {a_len} items")
        elif a_len != g_len:
            details.append(f"Length changed: {g_len} -> {a_len} items")

    # If elements are dicts, check key-set consistency
    if golden and isinstance(golden[0], dict) and actual and isinstance(actual[0], dict):
        golden_fields = set(golden[0].keys())
        actual_fields = set(actual[0].keys())
        missing_f = golden_fields - actual_fields
        new_f = actual_fields - golden_fields
        if missing_f:
            details.append(f"Record fields missing: {sorted(missing_f)}")
            all_ok = False
        if new_f:
            details.append(f"New record fields: {sorted(new_f)}")

    overlap = min(a_len, g_len) / max(g_len, 1)

    if not all_ok and overlap < 0.5:
        severity = "major"
    elif not all_ok:
        severity = "minor"
    elif a_len > g_len * 1.2:
        severity = "improved"
    else:
        severity = "none"

    return GoldenComparison(
        golden_path="(list comparison)",
        match=all_ok or severity in ("none", "improved"),
        severity=severity,
        topic_overlap=overlap,
        golden_age_days=0,
        summary="; ".join(details) if details else "All checks passed",
        details=details,
    )


def compare_to_golden(
    actual: dict | list | str,
    golden: dict | list | str,
    expected_keys: list[str] | None = None,
    expected_mentions: list[str] | None = None,
) -> GoldenComparison:
    """Compare actual result to golden, detecting regressions and improvements.

    Dispatches to the appropriate comparison strategy:
    - str vs str  -> topic-overlap comparison (Nestor-style)
    - dict vs dict -> structural key/type comparison
    - list vs list -> length and record-field comparison

    If types don't match, reports a major regression.
    """
    # Unwrap envelope if golden was saved with save_golden()
    if isinstance(golden, dict) and "meta" in golden and "data" in golden:
        golden = golden["data"]

    # String comparison (research reports, free-text outputs)
    if isinstance(actual, str) and isinstance(golden, str):
        return _compare_text_golden(actual, golden, expected_mentions)

    # Dict comparison
    if isinstance(actual, dict) and isinstance(golden, dict):
        return _compare_dict_golden(actual, golden, expected_keys)

    # List comparison
    if isinstance(actual, list) and isinstance(golden, list):
        return _compare_list_golden(actual, golden)

    # Type mismatch
    return GoldenComparison(
        golden_path="(type mismatch)",
        match=False,
        severity="major",
        topic_overlap=0.0,
        summary=f"Type mismatch: actual={type(actual).__name__}, golden={type(golden).__name__}",
        details=[f"Type mismatch: actual={type(actual).__name__}, golden={type(golden).__name__}"],
    )


# ---------------------------------------------------------------------------
# Pipeline golden snapshot
# ---------------------------------------------------------------------------


def snapshot_pipeline_golden(pipeline_name: str, config: dict | None = None) -> list[str]:
    """Snapshot current pipeline outputs as golden files.

    Reads each file in the pipeline's data_dir and saves it as a golden file
    under the 'pipeline' category.  Returns a list of saved golden paths.
    """
    from core.pipeline_checks import _resolve_pipelines

    if config is None:
        config = load_config()

    pipelines = _resolve_pipelines(config)
    if pipeline_name not in pipelines:
        raise ValueError(f"Unknown pipeline: {pipeline_name}. Known: {list(pipelines.keys())}")

    pc = pipelines[pipeline_name]
    data_dir = Path(pc.data_dir).expanduser()
    saved: list[str] = []

    for filename in pc.expected_files:
        filepath = data_dir / filename
        if not filepath.is_file():
            continue

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        golden_name = f"{pipeline_name}--{filename.replace('.json', '')}"
        path = save_golden("pipeline", golden_name, data)
        saved.append(str(path))

    return saved


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: golden.py [list|stale|snapshot <pipeline>]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        for g in list_golden_files():
            print(f"  {g['category']}/{g['name']}  ({g['age_days']}d old, {g['size_bytes']}B)")

    elif cmd == "stale":
        max_d = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        stale = check_golden_staleness(max_days=max_d)
        if stale:
            for g in stale:
                print(f"  STALE: {g['category']}/{g['name']} — {g['age_days']} days old")
        else:
            print(f"  No golden files older than {max_d} days.")

    elif cmd == "snapshot":
        if len(sys.argv) < 3:
            print("Usage: golden.py snapshot <pipeline-name>")
            sys.exit(1)
        saved = snapshot_pipeline_golden(sys.argv[2])
        for s in saved:
            print(f"  Saved: {s}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
