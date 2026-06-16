from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from core.config import load_config

# Signal type -> default value mapping
SIGNAL_VALUES = {
    "committed": 0.8,
    "deployed": 0.9,
    "heavy_edit": 0.3,
    "abandoned": 0.1,
    "quick_rating": None,  # Provided by caller
    "retrospective": None,
}


@dataclass
class FeedbackSignal:
    timestamp: str
    signal_type: str
    skill: str
    artifact_path: str
    value: float
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "signal_type": self.signal_type,
            "skill": self.skill,
            "artifact_path": self.artifact_path,
            "value": self.value,
            "meta": self.meta,
        }


def detect_commit_signal(diff_files: list[str]) -> list[FeedbackSignal]:
    now = datetime.now(timezone.utc).isoformat()
    signals = []

    for file_path in diff_files:
        path = Path(file_path)
        if path.suffix not in (".md", ".html", ".json", ".yaml", ".yml"):
            continue

        skill = _infer_skill_from_path(file_path)

        signals.append(FeedbackSignal(
            timestamp=now,
            signal_type="committed",
            skill=skill,
            artifact_path=file_path,
            value=SIGNAL_VALUES["committed"],
            meta={"source": "git_commit"},
        ))

    return signals


def detect_edit_distance(original: str, edited: str) -> float:
    if not original and not edited:
        return 0.0
    if not original or not edited:
        return 1.0
    ratio = SequenceMatcher(None, original, edited).ratio()
    return 1.0 - ratio


def append_feedback(signal: FeedbackSignal, config: dict | None = None) -> None:
    if config is None:
        config = load_config()

    feedback_dir = Path(config["feedback_dir"]).expanduser()
    feedback_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    feedback_file = feedback_dir / f"{today}.jsonl"

    with open(feedback_file, "a") as f:
        f.write(json.dumps(signal.to_dict()) + "\n")


def _infer_skill_from_path(file_path: str) -> str:
    lower = file_path.lower()

    skill_patterns = {
        "product-brief": ["brief", "prd", "spec"],
        "stakeholder-update": ["update", "status", "report"],
        "meeting-prep": ["meeting", "prep", "agenda"],
        "data-analyst": ["analysis", "analytics", "queries", "query"],
        "builder": ["script", "tool", "automation"],
        "writer": ["doc", "guide", "readme"],
        "prototype": ["prototype", "mock", "demo"],
    }

    for skill, patterns in skill_patterns.items():
        if any(p in lower for p in patterns):
            return skill

    return "unknown"
