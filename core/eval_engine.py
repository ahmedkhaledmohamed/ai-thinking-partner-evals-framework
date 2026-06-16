from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from core.config import DEFAULT_CONFIG, ensure_dirs, load_config

# Required sections per skill type.
# Keys are heading text (case-insensitive match against markdown headings).
SKILL_SECTIONS: dict[str, list[str]] = {
    "product-brief": [
        "Problem Statement",
        "Proposed Solution",
        "User Value",
        "Success Metrics",
        "Scope",
        "Open Questions",
        "Dependencies",
        "Timeline",
    ],
    "stakeholder-update": [
        "TL;DR",
        "Status",
        "Progress",
        "Key Metrics",
        "Risks",
        "Asks",
        "Next Period",
    ],
    "meeting-prep": [
        "Context",
        "Talking Points",
        "Anticipated Questions",
        "Preparation Checklist",
    ],
}

# Bonus markers that improve score when present
BONUS_PATTERNS = {
    "metrics_table": re.compile(r"^\|.+\|.+\|", re.MULTILINE),
    "actionability": re.compile(r"(?:- \[[ x]\]|action item|next step|TODO)", re.IGNORECASE),
    "quantified_target": re.compile(r"\d+%|\d+[KkMm]\b|[0-9]+\s*(?:users|MAU|DAU|subs)", re.IGNORECASE),
}

BONUS_WEIGHT = 0.05  # Each bonus adds up to this much to the overall score


@dataclass
class EvalResult:
    eval_id: str
    timestamp: str
    category: str
    tier: int
    skill: str
    eval_name: str
    input_summary: str
    scores: dict
    overall_score: float
    golden_match: bool
    regression: bool
    duration_ms: int
    meta: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "eval_id": self.eval_id,
            "timestamp": self.timestamp,
            "category": self.category,
            "tier": self.tier,
            "skill": self.skill,
            "eval_name": self.eval_name,
            "input_summary": self.input_summary,
            "scores": self.scores,
            "overall_score": self.overall_score,
            "golden_match": self.golden_match,
            "regression": self.regression,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
            "error": self.error,
        }


class EvalRunner:
    def __init__(self, config_path: str | Path | None = None):
        self.config = load_config(config_path)
        ensure_dirs(self.config)

    # ------------------------------------------------------------------
    # Tier 1: Structural check
    # ------------------------------------------------------------------

    def run_structural_check(self, file_path: str, skill: str) -> EvalResult:
        t0 = monotonic()
        path = Path(file_path).expanduser()

        if not path.exists():
            return self._error_result(
                skill=skill,
                eval_name="structural-check",
                error=f"File not found: {file_path}",
                duration_ms=int((monotonic() - t0) * 1000),
            )

        text = path.read_text(encoding="utf-8", errors="replace")

        if skill in ("unknown", "auto", ""):
            skill = self._detect_skill(text)

        required = SKILL_SECTIONS.get(skill, [])
        headings = self._extract_headings(text)
        heading_lower = {h.lower() for h in headings}

        section_scores: dict[str, float] = {}
        for section in required:
            found = section.lower() in heading_lower
            section_scores[section] = 1.0 if found else 0.0

        # Base score: fraction of required sections found
        if required:
            base_score = sum(section_scores.values()) / len(required)
        else:
            # No known template — give partial credit based on general structure
            base_score = min(len(headings) / 4, 1.0)  # At least 4 headings = 1.0

        # Bonus for quality markers
        bonus = 0.0
        bonus_hits: dict[str, bool] = {}
        for name, pattern in BONUS_PATTERNS.items():
            hit = bool(pattern.search(text))
            bonus_hits[name] = hit
            if hit:
                bonus += BONUS_WEIGHT

        overall = min(base_score + bonus, 1.0)

        # Check for regression against baseline
        regression = self._check_regression(skill, "structural-check", overall)

        duration_ms = int((monotonic() - t0) * 1000)

        return EvalResult(
            eval_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            category="structured_doc",
            tier=1,
            skill=skill,
            eval_name="section-completeness",
            input_summary=f"{path.name} ({len(text.split())} words, {len(headings)} headings)",
            scores={**section_scores, **{f"bonus_{k}": 1.0 if v else 0.0 for k, v in bonus_hits.items()}},
            overall_score=round(overall, 3),
            golden_match=True,  # No golden comparison for structural checks
            regression=regression,
            duration_ms=duration_ms,
            meta={
                "file_path": str(path),
                "word_count": len(text.split()),
                "heading_count": len(headings),
                "detected_skill": skill,
            },
        )

    # ------------------------------------------------------------------
    # Result persistence
    # ------------------------------------------------------------------

    def append_result(self, result: EvalResult) -> Path:
        results_dir = Path(self.config["results_dir"]).expanduser()
        results_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results_file = results_dir / f"{today}.jsonl"

        with open(results_file, "a") as f:
            f.write(json.dumps(result.to_dict()) + "\n")

        return results_file

    def load_results(self, days: int = 7) -> list[EvalResult]:
        results_dir = Path(self.config["results_dir"]).expanduser()
        if not results_dir.exists():
            return []

        results: list[EvalResult] = []
        today = datetime.now(timezone.utc)

        for i in range(days):
            date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            results_file = results_dir / f"{date_str}.jsonl"
            if not results_file.exists():
                continue

            with open(results_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        results.append(EvalResult(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue

        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_headings(self, text: str) -> list[str]:
        headings = []
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if match:
                headings.append(match.group(2).strip())
        return headings

    def _detect_skill(self, text: str) -> str:
        text_lower = text.lower()

        # Score each skill by how many of its required sections appear
        best_skill = "general"
        best_count = 0

        for skill, sections in SKILL_SECTIONS.items():
            count = sum(1 for s in sections if s.lower() in text_lower)
            if count > best_count:
                best_count = count
                best_skill = skill

        if best_count >= 2:
            return best_skill

        # Fallback heuristics for docs that don't match a template
        if re.search(r"(architecture|system design|service|api|grpc|protobuf|bigtable)", text_lower):
            return "technical-analyst"
        if re.search(r"(hypothesis|experiment|a/b test|control group|treatment)", text_lower):
            return "data-analyst"
        if re.search(r"(prototype|mockup|screen|phone frame|figma)", text_lower):
            return "prototype"
        if re.search(r"(strategy|vision|roadmap|mission|investment area)", text_lower):
            return "strategic-clarity"
        if re.search(r"(explore|brainstorm|trade-?off|option [a-c]|alternative)", text_lower):
            return "thought-partner"

        return "general"

    def _check_regression(self, skill: str, eval_name: str, current_score: float) -> bool:
        threshold_pct = self.config.get("thresholds", {}).get("regression_pct", 15)

        # Load recent results for comparison
        recent = self.load_results(days=7)
        matching = [
            r for r in recent
            if r.skill == skill and r.eval_name == eval_name and r.error is None
        ]

        if not matching:
            return False

        baseline = sum(r.overall_score for r in matching) / len(matching)
        drop_pct = ((baseline - current_score) / baseline * 100) if baseline > 0 else 0

        return drop_pct > threshold_pct

    def _error_result(self, skill: str, eval_name: str, error: str, duration_ms: int) -> EvalResult:
        return EvalResult(
            eval_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            category="structured_doc",
            tier=1,
            skill=skill,
            eval_name=eval_name,
            input_summary="",
            scores={},
            overall_score=0.0,
            golden_match=False,
            regression=False,
            duration_ms=duration_ms,
            error=error,
        )


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI Evals Framework")
    parser.add_argument("--check", type=str, help="Run structural check on a file")
    parser.add_argument("--skill", type=str, default="unknown", help="Skill that produced the file")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--days", type=int, default=7, help="Days of history to load")
    parser.add_argument("--summary", action="store_true", help="Print summary of recent results")

    args = parser.parse_args()
    runner = EvalRunner(config_path=args.config)

    if args.check:
        result = runner.run_structural_check(args.check, args.skill)
        runner.append_result(result)
        print(json.dumps(result.to_dict(), indent=2))

    elif args.summary:
        results = runner.load_results(days=args.days)
        if not results:
            print("No results found.")
            return

        scores = [r.overall_score for r in results if r.error is None]
        regressions = [r for r in results if r.regression]

        print(f"Results: {len(results)} evals over {args.days} days")
        print(f"Average score: {sum(scores) / len(scores):.3f}" if scores else "No scored results")
        print(f"Regressions: {len(regressions)}")

        by_skill: dict[str, list[float]] = {}
        for r in results:
            if r.error is None:
                by_skill.setdefault(r.skill, []).append(r.overall_score)

        if by_skill:
            print("\nBy skill:")
            for skill, skill_scores in sorted(by_skill.items()):
                avg = sum(skill_scores) / len(skill_scores)
                print(f"  {skill}: {avg:.3f} ({len(skill_scores)} evals)")


if __name__ == "__main__":
    main()
