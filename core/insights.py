"""Insights engine — analyzes eval patterns and generates improvement recommendations.

Reads eval data, identifies quality gaps, and proposes specific changes to
skills, CLAUDE.md, rubrics, and eval engine configuration.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev

from core.config import load_config
from core.eval_engine import EvalRunner, SKILL_SECTIONS


@dataclass
class Recommendation:
    target: str
    action: str
    description: str
    file_path: str
    impact: str
    evidence: dict = field(default_factory=dict)


def analyze_evals(days: int = 30) -> dict:
    runner = EvalRunner()
    results = runner.load_results(days=days)

    if not results:
        return {"low_performers": [], "misclassifications": [], "dimension_gaps": [],
                "detection_issues": [], "recommendations": [], "summary": "No eval data found."}

    by_skill = defaultdict(list)
    by_category = defaultdict(list)
    by_date = defaultdict(list)
    dimension_zeros = defaultdict(int)
    dimension_total = defaultdict(int)
    all_scores = []

    for r in results:
        by_skill[r.skill].append(r)
        by_category[r.category].append(r)
        by_date[r.timestamp[:10]].append(r)
        all_scores.append(r.overall_score)

        for dim, val in r.scores.items():
            if dim.startswith("bonus_"):
                continue
            dimension_total[dim] += 1
            if val == 0.0:
                dimension_zeros[dim] += 1

    low_performers = _find_low_performers(by_skill)
    misclassifications = _find_misclassifications(results)
    dimension_gaps = _find_dimension_gaps(dimension_zeros, dimension_total)
    detection_issues = _find_detection_issues(by_skill)
    trends = _compute_trends(by_date)
    recommendations = _generate_recommendations(
        low_performers, misclassifications, dimension_gaps, detection_issues, by_skill
    )

    overall_avg = mean(all_scores) if all_scores else 0
    return {
        "summary": f"{len(results)} evals across {len(by_date)} days. Overall avg: {overall_avg:.2f}.",
        "low_performers": low_performers,
        "misclassifications": misclassifications,
        "dimension_gaps": dimension_gaps,
        "detection_issues": detection_issues,
        "trends": trends,
        "recommendations": recommendations,
    }


def _find_low_performers(by_skill: dict) -> list[dict]:
    low = []
    for skill, evals in by_skill.items():
        scores = [e.overall_score for e in evals]
        avg = mean(scores)
        if avg < 0.6 and len(evals) >= 2:
            zero_rate = sum(1 for s in scores if s < 0.2) / len(scores)
            low.append({
                "skill": skill,
                "avg_score": round(avg, 3),
                "eval_count": len(evals),
                "zero_rate": round(zero_rate, 3),
                "worst_files": [e.input_summary for e in sorted(evals, key=lambda x: x.overall_score)[:3]],
                "likely_cause": "misclassification" if zero_rate > 0.5 else "genuine_quality_gap",
            })
    return sorted(low, key=lambda x: x["avg_score"])


def _find_misclassifications(results: list) -> list[dict]:
    misclassified = []
    for r in results:
        if r.skill not in SKILL_SECTIONS:
            continue
        required = SKILL_SECTIONS[r.skill]
        section_scores = {k: v for k, v in r.scores.items() if not k.startswith("bonus_")}
        if not section_scores:
            continue
        zero_sections = sum(1 for v in section_scores.values() if v == 0.0)
        total_sections = len(section_scores)
        if total_sections > 0 and zero_sections / total_sections > 0.7:
            misclassified.append({
                "file": r.input_summary,
                "detected_skill": r.skill,
                "score": r.overall_score,
                "missing_sections": [k for k, v in section_scores.items() if v == 0.0],
                "present_sections": [k for k, v in section_scores.items() if v == 1.0],
            })
    return misclassified[:20]


def _find_dimension_gaps(zeros: dict, totals: dict) -> list[dict]:
    gaps = []
    for dim, zero_count in zeros.items():
        total = totals.get(dim, 1)
        zero_rate = zero_count / total
        if zero_rate > 0.3 and total >= 5:
            gaps.append({
                "dimension": dim,
                "zero_rate": round(zero_rate, 3),
                "zero_count": zero_count,
                "total": total,
            })
    return sorted(gaps, key=lambda x: -x["zero_rate"])


def _find_detection_issues(by_skill: dict) -> list[dict]:
    issues = []
    for skill, evals in by_skill.items():
        if skill not in SKILL_SECTIONS:
            continue
        scores = [e.overall_score for e in evals]
        avg = mean(scores)
        very_low = sum(1 for s in scores if s < 0.2)
        if very_low / len(scores) > 0.5:
            issues.append({
                "skill": skill,
                "issue": "majority_score_below_0.2",
                "detail": f"{very_low}/{len(scores)} evals score below 0.2 — likely false positive detection",
                "avg_score": round(avg, 3),
            })

    if "general" in by_skill:
        gen_scores = [e.overall_score for e in by_skill["general"]]
        gen_avg = mean(gen_scores)
        perfect = sum(1 for s in gen_scores if s >= 0.95)
        if perfect / len(gen_scores) > 0.5:
            issues.append({
                "skill": "general",
                "issue": "inflated_scores",
                "detail": f"{perfect}/{len(gen_scores)} evals score >=0.95 — lenient fallback heuristic inflates scores",
                "avg_score": round(gen_avg, 3),
            })
    return issues


def _compute_trends(by_date: dict) -> list[dict]:
    trends = []
    dates = sorted(by_date.keys())
    for d in dates:
        evals = by_date[d]
        scores = [e.overall_score for e in evals]
        trends.append({
            "date": d,
            "avg_score": round(mean(scores), 3),
            "count": len(evals),
        })
    return trends


def _generate_recommendations(low_perf, misclass, dim_gaps, det_issues, by_skill) -> list[dict]:
    recs = []

    for issue in det_issues:
        if issue["issue"] == "majority_score_below_0.2":
            skill = issue["skill"]
            recs.append(Recommendation(
                target=f"eval_engine:detection:{skill}",
                action="tighten_detection",
                description=f"Skill '{skill}' has {issue['detail']}. Tighten detection to require 3+ heading matches instead of 2 body-text matches.",
                file_path="core/eval_engine.py",
                impact="high",
                evidence={"skill": skill, "avg_score": issue["avg_score"]},
            ).__dict__)

        if issue["issue"] == "inflated_scores":
            recs.append(Recommendation(
                target="eval_engine:general_scoring",
                action="improve_heuristic",
                description="'general' category uses min(headings/4, 1.0) which inflates scores. Replace with structural quality scoring (heading hierarchy, words per section, content markers).",
                file_path="core/eval_engine.py",
                impact="high",
                evidence={"avg_score": issue["avg_score"]},
            ).__dict__)

    for lp in low_perf:
        if lp["likely_cause"] == "genuine_quality_gap":
            skill = lp["skill"]
            skill_path = f"~/.claude/skills/{skill}/SKILL.md"
            recs.append(Recommendation(
                target=f"skill:{skill}",
                action="add_enforcement",
                description=f"Skill '{skill}' averages {lp['avg_score']}. Add a 'Required Output Structure' section to SKILL.md that enforces section compliance.",
                file_path=skill_path,
                impact="high",
                evidence=lp,
            ).__dict__)

    for gap in dim_gaps[:3]:
        recs.append(Recommendation(
            target=f"dimension:{gap['dimension']}",
            action="investigate",
            description=f"Dimension '{gap['dimension']}' is zero in {gap['zero_rate']*100:.0f}% of evals ({gap['zero_count']}/{gap['total']}). Either the check is too strict or outputs consistently miss this.",
            file_path="core/eval_engine.py",
            impact="medium",
            evidence=gap,
        ).__dict__)

    if misclass:
        count = len(misclass)
        top_skills = defaultdict(int)
        for m in misclass:
            top_skills[m["detected_skill"]] += 1
        worst = max(top_skills, key=top_skills.get)
        recs.append(Recommendation(
            target="eval_engine:detection",
            action="reduce_false_positives",
            description=f"{count} likely misclassifications detected. '{worst}' accounts for {top_skills[worst]}. Match against headings only, not body text.",
            file_path="core/eval_engine.py",
            impact="high",
            evidence={"total_misclassified": count, "by_skill": dict(top_skills)},
        ).__dict__)

    return recs


def format_insights_report(analysis: dict) -> str:
    lines = [f"# AI Evals Insights Report", ""]
    lines.append(f"## Summary")
    lines.append(analysis["summary"])
    lines.append("")

    if analysis["recommendations"]:
        lines.append(f"## Recommendations ({len(analysis['recommendations'])})")
        lines.append("")
        for i, rec in enumerate(analysis["recommendations"], 1):
            impact_icon = {"high": "!!!", "medium": "!!", "low": "!"}.get(rec["impact"], "")
            lines.append(f"### {i}. [{rec['impact'].upper()}] {rec['description']}")
            lines.append(f"- **Target**: `{rec['target']}`")
            lines.append(f"- **Action**: {rec['action']}")
            lines.append(f"- **File**: `{rec['file_path']}`")
            lines.append("")

    if analysis["low_performers"]:
        lines.append("## Low-Performing Skills")
        lines.append("")
        lines.append("| Skill | Avg Score | Evals | Zero Rate | Likely Cause |")
        lines.append("|-------|----------|-------|-----------|--------------|")
        for lp in analysis["low_performers"]:
            lines.append(f"| {lp['skill']} | {lp['avg_score']} | {lp['eval_count']} | {lp['zero_rate']*100:.0f}% | {lp['likely_cause']} |")
        lines.append("")

    if analysis["detection_issues"]:
        lines.append("## Detection Issues")
        lines.append("")
        for di in analysis["detection_issues"]:
            lines.append(f"- **{di['skill']}**: {di['detail']}")
        lines.append("")

    if analysis["dimension_gaps"]:
        lines.append("## Dimension Gaps")
        lines.append("")
        lines.append("| Dimension | Zero Rate | Count |")
        lines.append("|-----------|----------|-------|")
        for dg in analysis["dimension_gaps"]:
            lines.append(f"| {dg['dimension']} | {dg['zero_rate']*100:.0f}% | {dg['zero_count']}/{dg['total']} |")
        lines.append("")

    if analysis["misclassifications"]:
        lines.append(f"## Likely Misclassifications ({len(analysis['misclassifications'])})")
        lines.append("")
        for m in analysis["misclassifications"][:10]:
            lines.append(f"- **{m['file'][:60]}** → detected as `{m['detected_skill']}` (score {m['score']}), missing {len(m['missing_sections'])}/{len(m['missing_sections'])+len(m['present_sections'])} sections")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    analysis = analyze_evals(days=30)
    print(format_insights_report(analysis))
