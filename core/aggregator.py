from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean

from core.config import load_config
from core.eval_engine import EvalResult, EvalRunner


def aggregate_pr(results: list[EvalResult], pr_id: str) -> dict:
    if not results:
        return {"pr_id": pr_id, "score": 0.0, "breakdown": {}, "artifacts_evaluated": []}

    by_category: dict[str, list[float]] = {}
    artifacts = []

    for r in results:
        by_category.setdefault(r.category, []).append(r.overall_score)
        artifacts.append({
            "eval_id": r.eval_id,
            "eval_name": r.eval_name,
            "skill": r.skill,
            "score": r.overall_score,
            "input_summary": r.input_summary,
        })

    breakdown = {cat: mean(scores) for cat, scores in by_category.items()}
    overall = mean(r.overall_score for r in results)

    return {
        "pr_id": pr_id,
        "score": round(overall, 3),
        "breakdown": {k: round(v, 3) for k, v in breakdown.items()},
        "artifacts_evaluated": artifacts,
        "count": len(results),
        "regressions": sum(1 for r in results if r.regression),
    }


def aggregate_day(date: str, config: dict | None = None) -> dict:
    if config is None:
        config = load_config()

    runner = EvalRunner(config_path=None)
    runner.config = config

    results = _load_results_for_date(date, config)

    if not results:
        return {
            "date": date,
            "apqs": 0.0,
            "skill_usage": {},
            "highlight_best": None,
            "highlight_worst": None,
        }

    weights = config.get("scoring_weights", {})
    category_map = {
        "structured_doc": "structured_docs",
        "open_reasoning": "reasoning",
        "data_analysis": "data_analytics",
        "code_technical": "code_technical",
        "search_retrieval": "search_retrieval",
        "pipeline": "pipelines",
        "mcp_reliability": "mcp_reliability",
    }

    by_category: dict[str, list[float]] = {}
    by_skill: dict[str, int] = {}

    for r in results:
        by_category.setdefault(r.category, []).append(r.overall_score)
        by_skill[r.skill] = by_skill.get(r.skill, 0) + 1

    # Weighted APQS (AI Product Quality Score)
    apqs = 0.0
    total_weight = 0.0
    for cat, scores in by_category.items():
        weight_key = category_map.get(cat, cat)
        w = weights.get(weight_key, 0.1)
        apqs += w * mean(scores)
        total_weight += w

    apqs = apqs / total_weight if total_weight > 0 else 0.0

    sorted_results = sorted(results, key=lambda r: r.overall_score)
    worst = sorted_results[0]
    best = sorted_results[-1]

    return {
        "date": date,
        "apqs": round(apqs, 3),
        "skill_usage": by_skill,
        "count": len(results),
        "category_scores": {k: round(mean(v), 3) for k, v in by_category.items()},
        "highlight_best": {
            "eval_name": best.eval_name,
            "skill": best.skill,
            "score": best.overall_score,
        },
        "highlight_worst": {
            "eval_name": worst.eval_name,
            "skill": worst.skill,
            "score": worst.overall_score,
        },
    }


def aggregate_week(end_date: str, config: dict | None = None) -> dict:
    if config is None:
        config = load_config()

    end = datetime.strptime(end_date, "%Y-%m-%d")
    daily_aggregates = []
    all_results: list[EvalResult] = []

    for i in range(7):
        day = (end - timedelta(days=i)).strftime("%Y-%m-%d")
        day_results = _load_results_for_date(day, config)
        all_results.extend(day_results)

        if day_results:
            day_agg = aggregate_day(day, config)
            daily_aggregates.append(day_agg)

    if not daily_aggregates:
        return {
            "week_ending": end_date,
            "apqs_trend": [],
            "regressions": [],
            "improvements": [],
        }

    apqs_trend = [
        {"date": d["date"], "apqs": d["apqs"], "count": d["count"]}
        for d in sorted(daily_aggregates, key=lambda x: x["date"])
    ]

    # Detect regressions: results where regression=True
    regressions = [
        {
            "eval_name": r.eval_name,
            "skill": r.skill,
            "score": r.overall_score,
            "date": r.timestamp[:10],
        }
        for r in all_results if r.regression
    ]

    # Detect improvements: score > 0.9
    improvements = [
        {
            "eval_name": r.eval_name,
            "skill": r.skill,
            "score": r.overall_score,
            "date": r.timestamp[:10],
        }
        for r in all_results if r.overall_score > 0.9 and not r.regression
    ]

    week_apqs = mean(d["apqs"] for d in daily_aggregates) if daily_aggregates else 0.0

    return {
        "week_ending": end_date,
        "apqs": round(week_apqs, 3),
        "apqs_trend": apqs_trend,
        "regressions": regressions,
        "improvements": improvements,
        "total_evals": len(all_results),
        "days_with_data": len(daily_aggregates),
    }


def _load_results_for_date(date: str, config: dict) -> list[EvalResult]:
    from core.eval_engine import EvalRunner
    runner = EvalRunner.__new__(EvalRunner)
    runner.config = config
    # Load just the one day's results
    from pathlib import Path
    import json

    results_dir = Path(config["results_dir"]).expanduser()
    results_file = results_dir / f"{date}.jsonl"

    if not results_file.exists():
        return []

    results = []
    with open(results_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            results.append(EvalResult(**data))

    return results
