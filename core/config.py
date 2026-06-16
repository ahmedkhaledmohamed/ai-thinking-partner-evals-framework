from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "version": 1,
    "judge_model": "claude-sonnet-4-6",
    "results_dir": "~/.ai-evals/results",
    "golden_dir": "~/.ai-evals/golden",
    "feedback_dir": "~/.ai-evals/feedback",
    "reports_dir": "~/.ai-evals/reports",
    "categories": {
        "structured_doc": {
            "enabled": True,
            "tier": 1,
            "skills": ["product-brief", "stakeholder-update", "meeting-prep", "writer"],
        },
        "open_reasoning": {
            "enabled": True,
            "tier": 2,
            "skills": ["thought-partner", "devil-advocate", "strategic-clarity"],
        },
        "data_analysis": {
            "enabled": True,
            "tier": 2,
            "skills": ["data-analyst"],
        },
        "code_technical": {
            "enabled": True,
            "tier": 2,
            "skills": ["builder", "technical-analyst", "prototype"],
        },
        "search_retrieval": {
            "enabled": True,
            "tier": 2,
        },
        "pipeline": {
            "enabled": True,
            "tier": 1,
        },
        "mcp_reliability": {
            "enabled": True,
            "tier": 1,
        },
    },
    "thresholds": {
        "regression_pct": 15,
        "golden_staleness_days": 30,
        "pipeline_row_deviation_pct": 20,
    },
    "scoring_weights": {
        "structured_docs": 0.20,
        "reasoning": 0.15,
        "data_analytics": 0.15,
        "code_technical": 0.15,
        "search_retrieval": 0.10,
        "pipelines": 0.10,
        "mcp_reliability": 0.15,
    },
}

_DEFAULT_CONFIG_PATH = Path("~/.ai-evals/config.yaml")


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(path).expanduser() if path else _DEFAULT_CONFIG_PATH.expanduser()

    if config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        merged = {**DEFAULT_CONFIG, **user_config}
        # Deep-merge categories and thresholds
        for key in ("categories", "thresholds", "scoring_weights"):
            if key in user_config and key in DEFAULT_CONFIG:
                merged[key] = {**DEFAULT_CONFIG[key], **user_config[key]}
        return merged

    return dict(DEFAULT_CONFIG)


def ensure_dirs(config: dict) -> None:
    for key in ("results_dir", "golden_dir", "feedback_dir", "reports_dir"):
        dir_path = Path(config[key]).expanduser()
        dir_path.mkdir(parents=True, exist_ok=True)


def write_default_config(path: str | Path | None = None) -> Path:
    config_path = Path(path).expanduser() if path else _DEFAULT_CONFIG_PATH.expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
    return config_path
