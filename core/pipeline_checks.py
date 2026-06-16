"""
Data pipeline integrity validation.

Checks schema validity, freshness, row counts, and null fields
for Ahmed's data pipelines (product-catalog, orchestration-dashboard, etc.).

All check functions are independently callable — they don't require
the full pipeline runner.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from core.config import load_config


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    OK = "ok"


@dataclass
class PipelineCheck:
    pipeline: str  # "product-catalog", "orchestration-dashboard", etc.
    check_name: str  # "schema_valid", "freshness", "row_count", "null_check"
    severity: Severity
    passed: bool
    message: str
    value: Any = None  # The actual measured value
    threshold: Any = None  # The expected threshold

    def to_dict(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "check_name": self.check_name,
            "severity": self.severity.value,
            "passed": self.passed,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
        }


@dataclass
class PipelineConfig:
    name: str
    data_dir: str  # Path to data directory (supports ~ expansion)
    expected_files: list[str] = field(default_factory=list)
    freshness_hours: int = 48
    row_count_golden: dict[str, int] = field(default_factory=dict)  # filename -> expected row count
    critical_fields: dict[str, list[str]] = field(default_factory=dict)  # filename -> fields to null-check


# ---------------------------------------------------------------------------
# Default pipeline configurations for Ahmed's ecosystem
# ---------------------------------------------------------------------------

PIPELINES: dict[str, PipelineConfig] = {
    "product-catalog": PipelineConfig(
        name="Product Catalog",
        data_dir="~/Developer/Client-Messaging-Product-Catalog/site/data/",
        expected_files=[
            "moments.json",
            "push-performance.json",
            "reachability.json",
            "format-performance.json",
            "delivery-funnel.json",
            "use-case-breakdown.json",
            "social-metrics.json",
            "message-landscape.json",
            "message-landscape-segments.json",
            "optout-signals.json",
            "delivery-health.json",
            "user-frequency.json",
        ],
        freshness_hours=48,
        row_count_golden={},
        critical_fields={},
    ),
    "orchestration-dashboard": PipelineConfig(
        name="Orchestration Dashboard",
        data_dir="~/Developer/ClientMessaging/orchestration-dashboard/public/data/",
        expected_files=[
            "channel-health.json",
            "operators.json",
            "formats.json",
            "categories.json",
            "collision.json",
            "frequency-cap.json",
        ],
        freshness_hours=24,
        row_count_golden={},
        critical_fields={},
    ),
}


# ---------------------------------------------------------------------------
# Individual check functions (independently callable)
# ---------------------------------------------------------------------------


def check_directory_exists(data_dir: Path, pipeline_name: str) -> PipelineCheck:
    """Check that the pipeline data directory exists and is readable."""
    exists = data_dir.is_dir()
    return PipelineCheck(
        pipeline=pipeline_name,
        check_name="directory_exists",
        severity=Severity.OK if exists else Severity.WARNING,
        passed=exists,
        message=f"Directory {'exists' if exists else 'missing'}: {data_dir}",
        value=str(data_dir),
    )


def check_file_present(filepath: Path, pipeline_name: str) -> PipelineCheck:
    """Check that an expected file exists."""
    exists = filepath.is_file()
    return PipelineCheck(
        pipeline=pipeline_name,
        check_name="file_present",
        severity=Severity.OK if exists else Severity.CRITICAL,
        passed=exists,
        message=f"{'Found' if exists else 'MISSING'}: {filepath.name}",
        value=filepath.name,
    )


def check_file_schema(filepath: Path, pipeline_name: str = "") -> PipelineCheck:
    """Validate that a file contains parseable JSON with a sane top-level structure.

    Accepts list or dict at the top level. Rejects empty files and non-JSON.
    """
    pipeline_name = pipeline_name or filepath.parent.name

    if not filepath.is_file():
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="schema_valid",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"File not found: {filepath.name}",
            value=filepath.name,
        )

    try:
        text = filepath.read_text(encoding="utf-8")
        if not text.strip():
            return PipelineCheck(
                pipeline=pipeline_name,
                check_name="schema_valid",
                severity=Severity.CRITICAL,
                passed=False,
                message=f"Empty file: {filepath.name}",
                value=filepath.name,
            )

        data = json.loads(text)

        if not isinstance(data, (dict, list)):
            return PipelineCheck(
                pipeline=pipeline_name,
                check_name="schema_valid",
                severity=Severity.WARNING,
                passed=False,
                message=f"Unexpected top-level type ({type(data).__name__}): {filepath.name}",
                value=type(data).__name__,
                threshold="dict or list",
            )

        # For lists, check they aren't empty
        if isinstance(data, list) and len(data) == 0:
            return PipelineCheck(
                pipeline=pipeline_name,
                check_name="schema_valid",
                severity=Severity.WARNING,
                passed=False,
                message=f"Empty list in {filepath.name}",
                value=0,
                threshold=">0 items",
            )

        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="schema_valid",
            severity=Severity.OK,
            passed=True,
            message=f"Valid JSON ({type(data).__name__}): {filepath.name}",
            value=type(data).__name__,
        )

    except json.JSONDecodeError as e:
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="schema_valid",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"Invalid JSON in {filepath.name}: {e}",
            value=filepath.name,
        )
    except OSError as e:
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="schema_valid",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"Read error for {filepath.name}: {e}",
            value=filepath.name,
        )


def check_freshness(filepath: Path, threshold_hours: int, pipeline_name: str = "") -> PipelineCheck:
    """Check that a file was modified within *threshold_hours* of now."""
    pipeline_name = pipeline_name or filepath.parent.name

    if not filepath.is_file():
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="freshness",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"File not found: {filepath.name}",
            value=filepath.name,
            threshold=f"<{threshold_hours}h",
        )

    mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    age_hours = (now - mtime).total_seconds() / 3600

    passed = age_hours <= threshold_hours

    if passed:
        severity = Severity.OK
    elif age_hours <= threshold_hours * 2:
        severity = Severity.WARNING
    else:
        severity = Severity.CRITICAL

    return PipelineCheck(
        pipeline=pipeline_name,
        check_name="freshness",
        severity=severity,
        passed=passed,
        message=f"{filepath.name}: {age_hours:.1f}h old (threshold {threshold_hours}h)",
        value=round(age_hours, 1),
        threshold=threshold_hours,
    )


def check_row_count(
    filepath: Path,
    expected: int,
    deviation_pct: int = 20,
    pipeline_name: str = "",
) -> PipelineCheck:
    """Compare the number of items in a JSON list/dict to an expected count.

    For lists: len(data).
    For dicts: len(data) (top-level keys).
    Passes if actual is within *deviation_pct* of expected.
    """
    pipeline_name = pipeline_name or filepath.parent.name

    if not filepath.is_file():
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="row_count",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"File not found: {filepath.name}",
            value=None,
            threshold=expected,
        )

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="row_count",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"Cannot read {filepath.name}: {e}",
            value=None,
            threshold=expected,
        )

    if isinstance(data, list):
        actual = len(data)
    elif isinstance(data, dict):
        # Try to count a nested list if there's a single list-valued key,
        # otherwise count top-level keys.
        list_vals = [v for v in data.values() if isinstance(v, list)]
        if len(list_vals) == 1:
            actual = len(list_vals[0])
        else:
            actual = len(data)
    else:
        actual = 1

    if expected == 0:
        # No golden count set — just report the value
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="row_count",
            severity=Severity.INFO,
            passed=True,
            message=f"{filepath.name}: {actual} items (no golden baseline)",
            value=actual,
            threshold=None,
        )

    min_expected = expected * (1 - deviation_pct / 100)
    max_expected = expected * (1 + deviation_pct / 100)
    passed = min_expected <= actual <= max_expected

    if passed:
        severity = Severity.OK
    elif actual < min_expected * 0.5:
        severity = Severity.CRITICAL
    else:
        severity = Severity.WARNING

    deviation = ((actual - expected) / expected) * 100 if expected else 0

    return PipelineCheck(
        pipeline=pipeline_name,
        check_name="row_count",
        severity=severity,
        passed=passed,
        message=f"{filepath.name}: {actual} items ({deviation:+.0f}% vs expected {expected})",
        value=actual,
        threshold=expected,
    )


def check_nulls(
    filepath: Path,
    critical_fields: list[str] | None = None,
    pipeline_name: str = "",
) -> PipelineCheck:
    """Scan a JSON file for null values in critical fields.

    If *critical_fields* is provided, only those keys are checked.
    Otherwise, scan all top-level keys in each record.
    """
    pipeline_name = pipeline_name or filepath.parent.name

    if not filepath.is_file():
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="null_check",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"File not found: {filepath.name}",
            value=filepath.name,
        )

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="null_check",
            severity=Severity.CRITICAL,
            passed=False,
            message=f"Cannot read {filepath.name}: {e}",
            value=filepath.name,
        )

    # Normalise to a list of records
    if isinstance(data, dict):
        # If the dict has a single list-valued key, use that list
        list_vals = [v for v in data.values() if isinstance(v, list)]
        if len(list_vals) == 1 and all(isinstance(r, dict) for r in list_vals[0]):
            records = list_vals[0]
        else:
            records = [data]
    elif isinstance(data, list):
        records = [r for r in data if isinstance(r, dict)]
    else:
        records = []

    if not records:
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="null_check",
            severity=Severity.INFO,
            passed=True,
            message=f"{filepath.name}: no dict records to null-check",
            value=0,
        )

    null_counts: dict[str, int] = {}
    total_records = len(records)

    for record in records:
        fields_to_check = critical_fields if critical_fields else list(record.keys())
        for f in fields_to_check:
            if f in record and record[f] is None:
                null_counts[f] = null_counts.get(f, 0) + 1

    if not null_counts:
        return PipelineCheck(
            pipeline=pipeline_name,
            check_name="null_check",
            severity=Severity.OK,
            passed=True,
            message=f"{filepath.name}: no nulls in checked fields",
            value=0,
        )

    total_nulls = sum(null_counts.values())
    worst_field = max(null_counts, key=null_counts.get)  # type: ignore[arg-type]
    worst_pct = (null_counts[worst_field] / total_records) * 100

    # >50% null in a critical field is critical; any nulls are warning
    if critical_fields and worst_pct > 50:
        severity = Severity.CRITICAL
    elif worst_pct > 20:
        severity = Severity.WARNING
    else:
        severity = Severity.INFO

    details = ", ".join(f"{k}={v}/{total_records}" for k, v in null_counts.items())

    return PipelineCheck(
        pipeline=pipeline_name,
        check_name="null_check",
        severity=severity,
        passed=severity == Severity.INFO,
        message=f"{filepath.name}: {total_nulls} nulls ({details})",
        value=null_counts,
        threshold="0 nulls in critical fields",
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _resolve_pipelines(config: dict | None = None) -> dict[str, PipelineConfig]:
    """Merge default pipelines with any user overrides from config.yaml."""
    pipelines = dict(PIPELINES)

    if config is None:
        return pipelines

    user_pipelines = config.get("pipelines", {})
    for name, overrides in user_pipelines.items():
        if name in pipelines:
            base = pipelines[name]
            if "data_dir" in overrides:
                base.data_dir = overrides["data_dir"]
            if "expected_files" in overrides:
                base.expected_files = overrides["expected_files"]
            if "freshness_hours" in overrides:
                base.freshness_hours = overrides["freshness_hours"]
            if "row_count_golden" in overrides:
                base.row_count_golden = overrides["row_count_golden"]
            if "critical_fields" in overrides:
                base.critical_fields = overrides["critical_fields"]
        else:
            # User-defined pipeline
            pipelines[name] = PipelineConfig(
                name=overrides.get("name", name),
                data_dir=overrides.get("data_dir", ""),
                expected_files=overrides.get("expected_files", []),
                freshness_hours=overrides.get("freshness_hours", 48),
                row_count_golden=overrides.get("row_count_golden", {}),
                critical_fields=overrides.get("critical_fields", {}),
            )

    return pipelines


def check_pipeline(pipeline_config: PipelineConfig) -> list[PipelineCheck]:
    """Run all checks for a single pipeline. Returns list of check results."""
    checks: list[PipelineCheck] = []
    data_dir = Path(pipeline_config.data_dir).expanduser()
    name = pipeline_config.name

    # 1. Directory exists
    dir_check = check_directory_exists(data_dir, name)
    checks.append(dir_check)

    if not dir_check.passed:
        # No point running file-level checks if the directory is missing
        return checks

    # 2. Expected files present
    for filename in pipeline_config.expected_files:
        filepath = data_dir / filename
        checks.append(check_file_present(filepath, name))

    # 3. Per-file checks: schema, freshness, row count, null check
    for filename in pipeline_config.expected_files:
        filepath = data_dir / filename
        if not filepath.is_file():
            continue

        # Schema validation
        checks.append(check_file_schema(filepath, name))

        # Freshness
        checks.append(check_freshness(filepath, pipeline_config.freshness_hours, name))

        # Row count (if golden exists)
        expected_rows = pipeline_config.row_count_golden.get(filename, 0)
        if expected_rows > 0:
            deviation = 20  # Default; can be overridden via config
            checks.append(check_row_count(filepath, expected_rows, deviation, name))

        # Null check
        critical_fields = pipeline_config.critical_fields.get(filename)
        checks.append(check_nulls(filepath, critical_fields, name))

    return checks


def run_all_pipelines(
    pipeline_names: list[str] | None = None,
    config: dict | None = None,
) -> dict[str, list[PipelineCheck]]:
    """Run checks on specified pipelines (or all if None).

    Returns {pipeline_name: [PipelineCheck, ...]}.
    """
    if config is None:
        config = load_config()

    pipelines = _resolve_pipelines(config)

    if pipeline_names:
        pipelines = {k: v for k, v in pipelines.items() if k in pipeline_names}

    results: dict[str, list[PipelineCheck]] = {}
    for key, pipeline_config in pipelines.items():
        results[key] = check_pipeline(pipeline_config)

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_SEVERITY_ICONS = {
    Severity.CRITICAL: "CRIT",
    Severity.WARNING: "WARN",
    Severity.INFO: "INFO",
    Severity.OK: "OK",
}


def format_pipeline_report(results: dict[str, list[PipelineCheck]]) -> str:
    """Generate a markdown report from pipeline check results."""
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    lines.append(f"# Pipeline Integrity Report — {now.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")

    # Summary counts
    total = sum(len(checks) for checks in results.values())
    passed = sum(1 for checks in results.values() for c in checks if c.passed)
    criticals = sum(
        1 for checks in results.values()
        for c in checks
        if c.severity == Severity.CRITICAL and not c.passed
    )
    warnings = sum(
        1 for checks in results.values()
        for c in checks
        if c.severity == Severity.WARNING and not c.passed
    )

    lines.append("## Summary")
    lines.append(f"- **Total checks**: {total}")
    lines.append(f"- **Passed**: {passed}")
    lines.append(f"- **Critical failures**: {criticals}")
    lines.append(f"- **Warnings**: {warnings}")
    lines.append("")

    # Per-pipeline detail table
    for pipeline_name, checks in results.items():
        lines.append(f"## {pipeline_name}")
        lines.append("")
        lines.append("| Check | Status | Value | Threshold | Message |")
        lines.append("|-------|--------|-------|-----------|---------|")

        for c in checks:
            icon = _SEVERITY_ICONS.get(c.severity, "?")
            status = f"**{icon}**" if not c.passed else icon
            val = str(c.value) if c.value is not None else "-"
            thresh = str(c.threshold) if c.threshold is not None else "-"
            msg = c.message.replace("|", "\\|")
            lines.append(f"| {c.check_name} | {status} | {val} | {thresh} | {msg} |")

        lines.append("")

    # Highlight critical failures at the end
    if criticals > 0:
        lines.append("## Critical Failures")
        lines.append("")
        for pipeline_name, checks in results.items():
            for c in checks:
                if c.severity == Severity.CRITICAL and not c.passed:
                    lines.append(f"- **[{pipeline_name}]** {c.check_name}: {c.message}")
        lines.append("")

    lines.append(f"*Generated {now.isoformat()}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    names = sys.argv[1:] if len(sys.argv) > 1 else None
    results = run_all_pipelines(pipeline_names=names)
    print(format_pipeline_report(results))
