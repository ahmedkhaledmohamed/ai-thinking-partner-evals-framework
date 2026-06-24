"""Retroactive session evaluator.

Scans Claude Code session transcripts, extracts artifacts and conversation
quality signals, runs Tier 1 structural evals, and records results with
original timestamps so baselines backfill naturally.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from core.config import load_config, ensure_dirs
from core.eval_engine import EvalResult, EvalRunner, SKILL_SECTIONS, BONUS_PATTERNS

SESSIONS_ROOT = Path.home() / ".claude" / "projects"
CORRECTION_SIGNALS = ["no ", "wrong", "actually", "don't", "not that", "stop", "i meant", "that's not"]
SYCOPHANCY_OPENERS = re.compile(
    r"^\s*(?:great question|excellent|that's a great|wonderful|absolutely right|fantastic|love that)",
    re.IGNORECASE,
)


def find_sessions(project_filter: str = None, days: int = 30) -> list[Path]:
    sessions = []
    for proj_dir in SESSIONS_ROOT.iterdir():
        if not proj_dir.is_dir():
            continue
        if project_filter and project_filter not in proj_dir.name:
            continue
        for sf in proj_dir.glob("*.jsonl"):
            if "subagent" in str(sf):
                continue
            age_days = (datetime.now() - datetime.fromtimestamp(sf.stat().st_mtime)).days
            if age_days <= days:
                sessions.append(sf)
    return sorted(sessions, key=lambda f: f.stat().st_mtime)


def parse_session(session_path: Path) -> dict:
    """Extract evaluable signals from a session transcript."""
    result = {
        "session_id": session_path.stem,
        "date": datetime.fromtimestamp(session_path.stat().st_mtime).strftime("%Y-%m-%d"),
        "timestamp": datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "project": session_path.parent.name,
        "artifacts": [],       # Written .md files with content
        "text_blocks": [],     # Substantial AI text outputs
        "turn_count": 0,
        "human_turns": 0,
        "corrections": 0,
        "skills_used": [],
        "tools_called": defaultdict(int),
    }

    for line in open(session_path):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        if d.get("type") == "assistant":
            result["turn_count"] += 1
            for item in d.get("message", {}).get("content", []):
                if item.get("type") == "tool_use":
                    tool = item.get("name", "")
                    result["tools_called"][tool] += 1

                    if tool in ("Write", "Edit"):
                        fp = item.get("input", {}).get("file_path", "")
                        if fp and fp.endswith(".md") and not any(
                            x in fp for x in ["node_modules", ".git/", "__pycache__", "package-lock", "MEMORY.md"]
                        ):
                            content = item.get("input", {}).get("content", "")
                            if not content and tool == "Edit":
                                content = item.get("input", {}).get("new_string", "")
                            if content and len(content.split()) > 80:
                                result["artifacts"].append({
                                    "path": fp,
                                    "filename": Path(fp).name,
                                    "content": content,
                                    "word_count": len(content.split()),
                                })

                    if tool == "Skill":
                        skill_name = item.get("input", {}).get("skill", "")
                        if skill_name:
                            result["skills_used"].append(skill_name)

                if item.get("type") == "text":
                    text = item.get("text", "")
                    if len(text) > 300:
                        result["text_blocks"].append(text)

        elif d.get("type") == "human":
            result["human_turns"] += 1
            msg = ""
            for item in d.get("message", {}).get("content", []):
                if item.get("type") == "text":
                    msg += item.get("text", "").lower()
            if any(sig in msg for sig in CORRECTION_SIGNALS):
                result["corrections"] += 1

    result["tools_called"] = dict(result["tools_called"])
    return result


def eval_artifact(artifact: dict, session_date: str, session_id: str, runner: EvalRunner) -> EvalResult | None:
    """Run structural eval on an extracted artifact."""
    content = artifact["content"]
    filename = artifact["filename"]
    word_count = artifact["word_count"]

    # Skip plan files, memory files, config files
    if any(x in filename.lower() for x in ["plan", "memory", "claude.md", "skill.md", "config"]):
        return None

    # Skip HTML-heavy content (prototypes, presentations)
    html_tags = len(re.findall(r"<[a-z][^>]*>", content, re.IGNORECASE))
    if html_tags / max(word_count, 1) > 0.15 or content.strip().startswith("<!DOCTYPE"):
        return None

    # Detect skill from headings (not body text — avoids false positives)
    headings = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
    heading_texts = [h.strip().lower() for h in headings]

    skill = "general"
    best_count = 0
    for skill_name, sections in SKILL_SECTIONS.items():
        count = sum(1 for s in sections if s.lower() in heading_texts)
        if count > best_count:
            best_count = count
            skill = skill_name
    if best_count < 3:
        content_lower = content.lower()
        if re.search(r"(architecture|system design|service|api|grpc|protobuf|bigtable)", content_lower):
            skill = "technical-analyst"
        elif re.search(r"(hypothesis|experiment|a/b test|control group|treatment)", content_lower):
            skill = "data-analyst"
        elif re.search(r"(prototype|mockup|screen|phone frame|figma)", content_lower):
            skill = "prototype"
        elif re.search(r"(team identity|what we own|boundaries|team charter|capability audit)", content_lower):
            skill = "strategic-clarity"
        else:
            skill = "general"

    if skill in SKILL_SECTIONS:
        required = SKILL_SECTIONS[skill]
        found = sum(1 for req in required if any(req.lower() in h for h in heading_texts))
        section_score = found / len(required)
    else:
        # Check for table-heavy reference docs
        table_rows = len(re.findall(r"^\|.+\|", content, re.MULTILINE))
        total_lines = len([l for l in content.splitlines() if l.strip()])
        table_ratio = table_rows / max(total_lines, 1)

        if table_rows >= 5 and table_ratio > 0.3:
            t_score = min(table_rows / 10, 1.0) * 0.4
            h_score = min(len(headings) / 3, 1.0) * 0.2
            has_list_s = 0.1 if re.search(r"^[\s]*[-*]\s", content, re.MULTILINE) else 0.0
            has_meta = 0.15 if re.search(r"\*\*.*\*\*.*:", content) else 0.0
            depth = min(word_count / 200, 1.0) * 0.15
            raw_structural = min(t_score + h_score + has_list_s + has_meta + depth, 1.0)
        else:
            levels = set()
            for h in re.findall(r"^(#{1,6})\s", content, re.MULTILINE):
                levels.add(len(h))
            hierarchy = min(len(levels) / 3, 1.0) * 0.3
            h_presence = min(len(headings) / 6, 1.0) * 0.3
            has_table = 0.2 if re.search(r"^\|.+\|.+\|", content, re.MULTILINE) else 0.0
            has_list = 0.2 if re.search(r"^[\s]*[-*]\s", content, re.MULTILINE) else 0.0
            raw_structural = min(hierarchy + h_presence + has_table + has_list, 1.0)

        # Classify artifact maturity by path
        path_lower = artifact["path"].lower()
        is_draft = any(d in path_lower for d in ["sandbox", "planning", "context", "session-state", ".claude/plans"])
        if is_draft:
            section_score = 0.5 + (raw_structural * 0.5)
        else:
            section_score = raw_structural

    # Label general docs by maturity
    if skill == "general":
        path_lower = artifact["path"].lower()
        is_polished = any(d in path_lower for d in ["product-catalog", "topics", "strategy"])
        is_config = any(d in path_lower for d in ["/memory/", "/commands/", "/skills/", "/.claude/"])
        skill = "artifact" if is_polished and not is_config else "draft"

    # Bonus scoring
    bonus = 0.0
    for name, pattern in BONUS_PATTERNS.items():
        if pattern.search(content):
            bonus += 0.05
    bonus = min(bonus, 0.15)

    overall = min(section_score + bonus, 1.0)

    scores = {"section_coverage": section_score}
    for name, pattern in BONUS_PATTERNS.items():
        scores[f"bonus_{name}"] = 1.0 if pattern.search(content) else 0.0

    return EvalResult(
        eval_id=str(uuid.uuid4()),
        timestamp=f"{session_date}T12:00:00+00:00",
        category="structured_doc",
        tier=1,
        skill=skill,
        eval_name="section-completeness",
        input_summary=f"{filename} ({word_count} words, {len(headings)} headings)",
        scores=scores,
        overall_score=overall,
        golden_match=True,
        regression=overall < 0.6,
        duration_ms=0,
        meta={
            "file_path": artifact["path"],
            "word_count": word_count,
            "heading_count": len(headings),
            "detected_skill": skill,
            "source": "retroactive",
            "session_id": session_id,
        },
    )


def eval_conversation_quality(session: dict) -> EvalResult | None:
    """Evaluate conversation-level quality signals."""
    text_blocks = session["text_blocks"]
    if len(text_blocks) < 3:
        return None

    scores = {}

    # Sycophancy rate
    syc_count = sum(1 for t in text_blocks if SYCOPHANCY_OPENERS.search(t))
    scores["non_sycophancy"] = 1.0 - (syc_count / len(text_blocks))

    # Depth: avg length of substantive responses
    avg_len = mean(len(t.split()) for t in text_blocks)
    scores["response_depth"] = min(avg_len / 300, 1.0)

    # Correction rate (lower is better)
    if session["human_turns"] > 0:
        correction_rate = session["corrections"] / session["human_turns"]
        scores["low_correction_rate"] = max(1.0 - correction_rate * 3, 0.0)
    else:
        scores["low_correction_rate"] = 1.0

    # Specificity: presence of code refs, file paths, metric numbers
    specific_count = 0
    for t in text_blocks:
        if re.search(r"(/[\w/.-]+\.\w+|`[a-zA-Z_]+\(|[0-9]+%|\d+[KkMm]\b)", t):
            specific_count += 1
    scores["specificity"] = min(specific_count / len(text_blocks) * 1.5, 1.0)

    # Tool usage (more tools = more grounded)
    tool_count = sum(session["tools_called"].values())
    scores["tool_grounding"] = min(tool_count / (session["turn_count"] * 0.5 + 1), 1.0)

    weights = {
        "non_sycophancy": 0.25,
        "response_depth": 0.20,
        "low_correction_rate": 0.20,
        "specificity": 0.20,
        "tool_grounding": 0.15,
    }
    overall = sum(scores[k] * weights[k] for k in weights)

    COMMAND_NOISE = {"eval:rate", "eval:run", "eval:check", "eval:pipeline",
                     "eval:report", "eval:regression", "eval:calibrate", "eval:improve",
                     "loop", "update-config", "impact-log:impact-log", "schedule"}
    skills = [s for s in session["skills_used"] if s not in COMMAND_NOISE and ":" not in s]
    primary_skill = max(set(skills), key=skills.count) if skills else "conversation"

    return EvalResult(
        eval_id=str(uuid.uuid4()),
        timestamp=session["timestamp"],
        category="open_reasoning",
        tier=1,
        skill=primary_skill,
        eval_name="conversation-quality",
        input_summary=f"Session {session['session_id'][:8]} ({session['turn_count']} turns, {len(text_blocks)} text blocks)",
        scores=scores,
        overall_score=round(overall, 3),
        golden_match=True,
        regression=overall < 0.6,
        duration_ms=0,
        meta={
            "session_id": session["session_id"],
            "date": session["date"],
            "turn_count": session["turn_count"],
            "human_turns": session["human_turns"],
            "corrections": session["corrections"],
            "skills_used": list(set(skills)),
            "tools_called": session["tools_called"],
            "artifact_count": len(session["artifacts"]),
            "source": "retroactive",
        },
    )


def eval_session_metrics(session: dict) -> EvalResult | None:
    """Evaluate session-level efficiency metrics."""
    if session["turn_count"] < 3:
        return None

    scores = {}

    # Efficiency: artifacts per turn
    artifact_count = len(session["artifacts"])
    scores["artifact_yield"] = min(artifact_count / max(session["turn_count"] * 0.1, 1), 1.0)

    # Focus: fewer corrections = more aligned
    if session["human_turns"] > 0:
        scores["alignment"] = max(1.0 - (session["corrections"] / session["human_turns"]) * 2, 0.0)
    else:
        scores["alignment"] = 0.8

    # Tool diversity: used multiple tool types
    unique_tools = len(session["tools_called"])
    scores["tool_diversity"] = min(unique_tools / 5, 1.0)

    # Completion: session produced artifacts (not just chat)
    scores["completion"] = 1.0 if artifact_count > 0 else 0.4

    weights = {"artifact_yield": 0.30, "alignment": 0.30, "tool_diversity": 0.15, "completion": 0.25}
    overall = sum(scores[k] * weights[k] for k in weights)

    return EvalResult(
        eval_id=str(uuid.uuid4()),
        timestamp=session["timestamp"],
        category="code_technical",
        tier=1,
        skill="session-efficiency",
        eval_name="session-metrics",
        input_summary=f"Session {session['session_id'][:8]} ({session['turn_count']}t, {artifact_count} artifacts, {session['corrections']}c)",
        scores=scores,
        overall_score=round(overall, 3),
        golden_match=True,
        regression=False,
        duration_ms=0,
        meta={
            "session_id": session["session_id"],
            "date": session["date"],
            "source": "retroactive",
        },
    )


def sync_date(target_date: str, project_filter: str = None) -> int:
    """Sync evals for a specific date. Scans sessions modified on that date,
    evaluates any unevaluated artifacts, and appends to the JSONL file.
    Returns the number of new evals written."""
    config = load_config()
    ensure_dirs(config)
    runner = EvalRunner()

    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    sessions = []
    for proj_dir in SESSIONS_ROOT.iterdir():
        if not proj_dir.is_dir():
            continue
        if project_filter and project_filter not in proj_dir.name:
            continue
        for sf in proj_dir.glob("*.jsonl"):
            if "subagent" in str(sf):
                continue
            mod_date = datetime.fromtimestamp(sf.stat().st_mtime).date()
            if mod_date == target:
                sessions.append(sf)

    if not sessions:
        return 0

    results_dir = Path(config["results_dir"]).expanduser()
    results_dir.mkdir(parents=True, exist_ok=True)
    filepath = results_dir / f"{target_date}.jsonl"

    existing_retro = set()
    if filepath.exists():
        for line in open(filepath):
            try:
                d = json.loads(line)
                if d.get("meta", {}).get("source") == "retroactive":
                    existing_retro.add(d.get("meta", {}).get("session_id", "") + d.get("eval_name", ""))
            except (json.JSONDecodeError, KeyError):
                pass

    written = 0
    for sf in sessions:
        session = parse_session(sf)
        new_results = []

        for artifact in session["artifacts"]:
            result = eval_artifact(artifact, target_date, session["session_id"], runner)
            if result:
                new_results.append(result)

        conv = eval_conversation_quality(session)
        if conv:
            new_results.append(conv)

        metrics = eval_session_metrics(session)
        if metrics:
            new_results.append(metrics)

        fresh = [r for r in new_results
                 if (r.meta.get("session_id", "") + r.eval_name) not in existing_retro]

        if fresh:
            with open(filepath, "a") as f:
                for r in fresh:
                    f.write(json.dumps({
                        "eval_id": r.eval_id, "timestamp": r.timestamp, "category": r.category,
                        "tier": r.tier, "skill": r.skill, "eval_name": r.eval_name,
                        "input_summary": r.input_summary, "scores": r.scores,
                        "overall_score": r.overall_score, "golden_match": r.golden_match,
                        "regression": r.regression, "duration_ms": r.duration_ms,
                        "meta": r.meta, "error": r.error,
                    }) + "\n")
                    written += 1

    return written


def run_retroactive(project_filter: str = "ClientMessaging", days: int = 30, dry_run: bool = False):
    """Run retroactive evals on past sessions."""
    config = load_config()
    ensure_dirs(config)
    runner = EvalRunner()
    sessions = find_sessions(project_filter, days)

    print(f"Found {len(sessions)} sessions in last {days} days")

    all_results = []
    by_date = defaultdict(list)

    for sf in sessions:
        session = parse_session(sf)
        date = session["date"]
        sid = session["session_id"][:8]

        # 1. Eval each artifact
        for artifact in session["artifacts"]:
            result = eval_artifact(artifact, date, session["session_id"], runner)
            if result:
                all_results.append(result)
                by_date[date].append(result)

        # 2. Eval conversation quality
        conv_result = eval_conversation_quality(session)
        if conv_result:
            all_results.append(conv_result)
            by_date[date].append(conv_result)

        # 3. Eval session metrics
        metrics_result = eval_session_metrics(session)
        if metrics_result:
            all_results.append(metrics_result)
            by_date[date].append(metrics_result)

    print(f"\nGenerated {len(all_results)} eval results across {len(by_date)} days")
    print(f"  Artifact evals: {sum(1 for r in all_results if r.eval_name == 'section-completeness')}")
    print(f"  Conversation evals: {sum(1 for r in all_results if r.eval_name == 'conversation-quality')}")
    print(f"  Session metric evals: {sum(1 for r in all_results if r.eval_name == 'session-metrics')}")

    if dry_run:
        print("\n[DRY RUN] Would write to:")
        for date in sorted(by_date.keys()):
            print(f"  ~/.ai-evals/results/{date}.jsonl ({len(by_date[date])} entries)")
        return all_results

    # Write results to date-partitioned JSONL files
    results_dir = Path(config["results_dir"]).expanduser()
    results_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for date, results in sorted(by_date.items()):
        filepath = results_dir / f"{date}.jsonl"
        # Check for existing retroactive entries to avoid duplicates
        existing_retro = set()
        if filepath.exists():
            for line in open(filepath):
                try:
                    d = json.loads(line)
                    if d.get("meta", {}).get("source") == "retroactive":
                        existing_retro.add(d.get("meta", {}).get("session_id", "") + d.get("eval_name", ""))
                except:
                    pass

        new_results = [
            r for r in results
            if (r.meta.get("session_id", "") + r.eval_name) not in existing_retro
        ]

        if new_results:
            with open(filepath, "a") as f:
                for r in new_results:
                    f.write(json.dumps(r.__dict__ if hasattr(r, '__dict__') else {
                        "eval_id": r.eval_id, "timestamp": r.timestamp, "category": r.category,
                        "tier": r.tier, "skill": r.skill, "eval_name": r.eval_name,
                        "input_summary": r.input_summary, "scores": r.scores,
                        "overall_score": r.overall_score, "golden_match": r.golden_match,
                        "regression": r.regression, "duration_ms": r.duration_ms,
                        "meta": r.meta, "error": r.error,
                    }) + "\n")
                    written += 1

    print(f"\nWrote {written} new entries ({len(all_results) - written} skipped as duplicates)")

    # Print per-date summary
    print(f"\nPer-date breakdown:")
    for date in sorted(by_date.keys()):
        results = by_date[date]
        avg = mean(r.overall_score for r in results)
        print(f"  {date}: {len(results)} evals, avg score {avg:.2f}")

    return all_results


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    days = 30
    for arg in sys.argv[1:]:
        if arg.isdigit():
            days = int(arg)
    run_retroactive(days=days, dry_run=dry)
