"""MCP reliability smoke tests.

Checks MCP server availability and tracks known quirks.
Reads server config from ~/.claude/settings.json to discover
which MCP servers are in use, then validates reachability for
URL-type servers and documents known behavioral quirks.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class McpCheck:
    server_name: str
    check_name: str  # "reachable", "known_quirk", "config_valid"
    passed: bool
    latency_ms: int
    message: str
    severity: str  # "ok", "warning", "critical", "info"

    def to_dict(self) -> dict:
        return {
            "server_name": self.server_name,
            "check_name": self.check_name,
            "passed": self.passed,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "severity": self.severity,
        }


# Documented MCP quirks discovered through usage.
# Keys match server names in ~/.claude/settings.json -> mcpServers.
KNOWN_QUIRKS: dict[str, dict[str, str]] = {
    "groove-mcp": {
        "name": "additionalOrgs field unreliable",
        "description": (
            "get-definition-of-done response may omit or partially return "
            "additionalOrgs. Observed on DOD-8800 (field absent) and DOD-8189 "
            "(omitted Delivery Pod despite UI showing it)."
        ),
        "workaround": (
            "Use indirectOrgs filter on list-definitions-of-done as the "
            "canonical signal. Never disprove a tag from the detail call alone."
        ),
    },
    "code-search": {
        "name": "uppercase OR treated as literal",
        "description": (
            "Zoekt treats uppercase OR as a literal search term, not a "
            "boolean operator. Queries like 'cache OR redis' search for "
            "the literal string 'OR'."
        ),
        "workaround": "Use lowercase 'or' or pipe '|' for alternation.",
    },
    "bigquery-mcp": {
        "name": "old partitions may 404",
        "description": (
            "Querying very old date partitions may return table-not-found "
            "errors even when the table exists with newer partitions."
        ),
        "workaround": (
            "Always check partition availability with "
            "INFORMATION_SCHEMA.PARTITIONS before querying historical data."
        ),
    },
    "google-drive": {
        "name": "mime_type omission creates Google Doc",
        "description": (
            "When creating a file via the Drive MCP, omitting mime_type "
            "defaults to Google Doc format. Setting mime_type='text/html' "
            "creates an HTML file, not a Doc."
        ),
        "workaround": (
            "Omit mime_type to create a Google Doc from HTML content. "
            "Only set mime_type explicitly when you want a non-Doc format."
        ),
    },
    "text2sql-mcp": {
        "name": "may generate invalid table references",
        "description": (
            "Natural language queries about uncommon tables can produce "
            "SQL referencing non-existent datasets or wrong project IDs."
        ),
        "workaround": (
            "Always validate generated SQL table references before execution. "
            "Cross-check with bigquery-mcp or INFORMATION_SCHEMA."
        ),
    },
}


def load_mcp_config() -> dict:
    """Load MCP server config from ~/.claude/settings.json.

    Returns the mcpServers dict, or empty dict if file missing/malformed.
    """
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("mcpServers", {})


def check_config_valid(name: str, config: dict) -> McpCheck:
    """Validate that a server config has required fields."""
    server_type = config.get("type", "")
    if not server_type:
        return McpCheck(
            name, "config_valid", False, 0,
            f"{name}: missing 'type' field in config",
            "warning",
        )

    if server_type == "url" and not config.get("url"):
        return McpCheck(
            name, "config_valid", False, 0,
            f"{name}: url-type server missing 'url' field",
            "critical",
        )

    if server_type == "stdio":
        command = config.get("command", "")
        if not command:
            return McpCheck(
                name, "config_valid", False, 0,
                f"{name}: stdio server missing 'command' field",
                "critical",
            )
        cmd_path = Path(command)
        if not cmd_path.exists():
            return McpCheck(
                name, "config_valid", False, 0,
                f"{name}: command binary not found at {command}",
                "warning",
            )

    return McpCheck(
        name, "config_valid", True, 0,
        f"{name}: config valid ({server_type})",
        "ok",
    )


def check_mcp_reachable(name: str, config: dict) -> McpCheck:
    """Check if an MCP server URL is reachable (HTTP HEAD with timeout).

    Only meaningful for 'url' type servers. Stdio servers are local
    processes and assumed reachable if config is valid.
    """
    server_type = config.get("type", "unknown")
    url = config.get("url", "")

    if server_type == "stdio":
        return McpCheck(
            name, "reachable", True, 0,
            f"{name}: stdio server (local process, assumed OK)",
            "ok",
        )

    if not url:
        return McpCheck(
            name, "reachable", False, 0,
            f"{name}: no URL configured",
            "warning",
        )

    start = datetime.now()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "ai-evals-mcp-check/1.0")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            latency = int((datetime.now() - start).total_seconds() * 1000)
            return McpCheck(
                name, "reachable", True, latency,
                f"{name}: reachable ({resp.status}, {latency}ms)",
                "ok",
            )
    except urllib.error.HTTPError as e:
        latency = int((datetime.now() - start).total_seconds() * 1000)
        # 401/403/405 means server is up but requires auth or rejects HEAD
        if e.code in (401, 403, 405):
            return McpCheck(
                name, "reachable", True, latency,
                f"{name}: reachable (HTTP {e.code} — auth/method restriction, {latency}ms)",
                "ok",
            )
        return McpCheck(
            name, "reachable", False, latency,
            f"{name}: HTTP {e.code} ({latency}ms)",
            "warning",
        )
    except urllib.error.URLError as e:
        latency = int((datetime.now() - start).total_seconds() * 1000)
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        return McpCheck(
            name, "reachable", False, latency,
            f"{name}: unreachable (URLError: {reason})",
            "critical",
        )
    except TimeoutError:
        return McpCheck(
            name, "reachable", False, 10000,
            f"{name}: timed out after 10s",
            "critical",
        )
    except Exception as e:
        latency = int((datetime.now() - start).total_seconds() * 1000)
        return McpCheck(
            name, "reachable", False, latency,
            f"{name}: unreachable ({type(e).__name__}: {e})",
            "critical",
        )


def check_known_quirks(name: str) -> list[McpCheck]:
    """Return known quirk warnings for a server."""
    if name not in KNOWN_QUIRKS:
        return []
    quirk = KNOWN_QUIRKS[name]
    return [
        McpCheck(
            name, "known_quirk", True, 0,
            f"{name}: {quirk['name']} — {quirk['workaround']}",
            "info",
        )
    ]


def run_mcp_checks() -> list[McpCheck]:
    """Run all MCP checks: config validation, reachability, and quirk documentation."""
    config = load_mcp_config()
    checks: list[McpCheck] = []

    if not config:
        checks.append(
            McpCheck(
                "__global__", "config_valid", False, 0,
                "No MCP servers found in ~/.claude/settings.json",
                "critical",
            )
        )
        return checks

    for name, server_config in sorted(config.items()):
        checks.append(check_config_valid(name, server_config))
        checks.append(check_mcp_reachable(name, server_config))
        checks.extend(check_known_quirks(name))

    return checks


def summarize_checks(checks: list[McpCheck]) -> dict:
    """Return a summary dict suitable for aggregation/reporting."""
    reachable = [c for c in checks if c.check_name == "reachable"]
    config_checks = [c for c in checks if c.check_name == "config_valid"]
    quirks = [c for c in checks if c.check_name == "known_quirk"]

    up = sum(1 for c in reachable if c.passed)
    total = len(reachable)
    configs_ok = sum(1 for c in config_checks if c.passed)
    avg_latency = (
        round(sum(c.latency_ms for c in reachable if c.passed and c.latency_ms > 0)
              / max(1, sum(1 for c in reachable if c.passed and c.latency_ms > 0)))
        if any(c.passed and c.latency_ms > 0 for c in reachable)
        else 0
    )

    critical = [c for c in checks if c.severity == "critical" and not c.passed]

    return {
        "servers_configured": total,
        "servers_reachable": up,
        "configs_valid": configs_ok,
        "known_quirks": len(quirks),
        "avg_latency_ms": avg_latency,
        "critical_failures": [c.to_dict() for c in critical],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def format_mcp_report(checks: list[McpCheck]) -> str:
    """Generate a markdown report from check results."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# MCP Reliability Report — {ts}", ""]

    summary = summarize_checks(checks)

    lines.append("## Summary")
    lines.append(f"- **Servers configured**: {summary['servers_configured']}")
    lines.append(f"- **Reachable**: {summary['servers_reachable']}/{summary['servers_configured']}")
    lines.append(f"- **Configs valid**: {summary['configs_valid']}/{summary['servers_configured']}")
    lines.append(f"- **Average latency**: {summary['avg_latency_ms']}ms")
    lines.append(f"- **Known quirks documented**: {summary['known_quirks']}")
    lines.append("")

    # Config validity
    config_checks = [c for c in checks if c.check_name == "config_valid"]
    if config_checks:
        lines.append("## Config Validation")
        lines.append("")
        lines.append("| Server | Status | Details |")
        lines.append("|--------|--------|---------|")
        for c in sorted(config_checks, key=lambda x: x.server_name):
            status = "OK" if c.passed else f"**{c.severity.upper()}**"
            detail = c.message.split(": ", 1)[-1] if ": " in c.message else c.message
            lines.append(f"| {c.server_name} | {status} | {detail} |")
        lines.append("")

    # Reachability
    reachable = [c for c in checks if c.check_name == "reachable"]
    if reachable:
        lines.append("## Connectivity")
        lines.append("")
        lines.append("| Server | Status | Latency | Details |")
        lines.append("|--------|--------|---------|---------|")
        for c in sorted(reachable, key=lambda x: x.server_name):
            status = "OK" if c.passed else f"**{c.severity.upper()}**"
            latency = f"{c.latency_ms}ms" if c.latency_ms > 0 else "-"
            detail = c.message.split(": ", 1)[-1] if ": " in c.message else c.message
            lines.append(f"| {c.server_name} | {status} | {latency} | {detail} |")
        lines.append("")

    # Known quirks
    quirks = [c for c in checks if c.check_name == "known_quirk"]
    if quirks:
        lines.append("## Known Quirks")
        lines.append("")
        for c in sorted(quirks, key=lambda x: x.server_name):
            detail = c.message.split(": ", 1)[-1] if ": " in c.message else c.message
            lines.append(f"- **{c.server_name}**: {detail}")
        lines.append("")

    # Critical failures callout
    critical = [c for c in checks if c.severity == "critical" and not c.passed]
    if critical:
        lines.append("## Critical Failures")
        lines.append("")
        for c in critical:
            lines.append(f"- **{c.server_name}** ({c.check_name}): {c.message}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    checks = run_mcp_checks()
    print(format_mcp_report(checks))
