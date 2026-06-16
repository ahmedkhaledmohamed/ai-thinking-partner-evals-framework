"""LLM-as-Judge engine for AI output evaluation.

Uses claude --print subprocess to judge AI-generated outputs against
markdown rubrics. Separates evaluation context from generation context
to avoid contamination.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic


@dataclass
class JudgeResult:
    rubric_name: str
    dimensions: dict[str, float]        # {"completeness": 0.85, "evidence": 0.7, ...}
    weights: dict[str, float]           # {"completeness": 0.25, ...}
    overall_score: float                # Weighted composite
    weaknesses: list[str]               # Required: at least 1 for scores >= 0.8
    anti_patterns_found: list[str]      # Sycophancy, verbosity, etc.
    penalty: float                      # Total penalty from anti-patterns
    raw_response: str                   # Full judge response for debugging
    model: str                          # Which model judged
    error: str | None = None
    duration_ms: int = 0


# --------------------------------------------------------------------------
# Anti-pattern definitions
# --------------------------------------------------------------------------

_SYCOPHANTIC_OPENERS = re.compile(
    r"^\s*(?:great question|excellent|that'?s a great (?:idea|point|question)|wonderful|"
    r"absolutely right|you'?re (?:absolutely |totally )?right|fantastic question|"
    r"love that|what a great)",
    re.IGNORECASE,
)

_MOTIVATIONAL_LANGUAGE = re.compile(
    r"(?:this will transform|game[- ]changing|revolutionary|paradigm[- ]shift|"
    r"unlock incredible|truly groundbreaking|this is going to be amazing)",
    re.IGNORECASE,
)

_HEDGE_WORDS = re.compile(
    r"\b(?:might|perhaps|possibly|maybe|potentially|could potentially)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def load_rubric(rubric_path: str | Path) -> tuple[str, dict[str, float]]:
    """Load rubric markdown and extract dimension weights.

    Parses headers of the form:
        ## Dimension Name (weight: 0.25)
    to extract weights. Returns (rubric_text, weights_dict).
    """
    path = Path(rubric_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Rubric not found: {path}")

    rubric_text = path.read_text(encoding="utf-8")

    # Extract weights from ## headers with (weight: X.XX) pattern
    weight_pattern = re.compile(
        r"^##\s+(.+?)\s*\(weight:\s*([\d.]+)\)\s*$",
        re.MULTILINE,
    )

    weights: dict[str, float] = {}
    for match in weight_pattern.finditer(rubric_text):
        dim_name = match.group(1).strip().lower().replace(" ", "_")
        weight_val = float(match.group(2))
        weights[dim_name] = weight_val

    if not weights:
        raise ValueError(f"No dimension weights found in rubric: {path}")

    # Validate weights sum to ~1.0 (allow small float drift)
    total = sum(weights.values())
    if abs(total - 1.0) > 0.05:
        raise ValueError(
            f"Dimension weights sum to {total:.2f}, expected ~1.0 in {path}"
        )

    return rubric_text, weights


def judge(
    output: str,
    rubric_path: str | Path,
    context: dict | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> JudgeResult:
    """Run LLM-as-judge on an output.

    1. Load rubric from file
    2. Construct prompt with rubric + output + context
    3. Execute via claude --print subprocess
    4. Parse JSON response
    5. Apply anti-pattern penalties
    6. Validate: require at least 1 weakness for scores >= 0.8
    """
    t0 = monotonic()
    rubric_path = Path(rubric_path).expanduser()
    rubric_name = rubric_path.stem

    try:
        rubric_text, weights = load_rubric(rubric_path)
    except (FileNotFoundError, ValueError) as e:
        return JudgeResult(
            rubric_name=rubric_name,
            dimensions={},
            weights={},
            overall_score=0.0,
            weaknesses=[],
            anti_patterns_found=[],
            penalty=0.0,
            raw_response="",
            model=model,
            error=str(e),
            duration_ms=int((monotonic() - t0) * 1000),
        )

    # Detect anti-patterns on the ORIGINAL output (not judge response)
    anti_patterns, penalty = _detect_anti_patterns(output)

    # Build the judge prompt
    prompt_parts = [
        "You are an impartial, critical evaluator. Follow the rubric precisely.",
        "",
        "=== RUBRIC ===",
        rubric_text,
        "",
        "=== OUTPUT TO EVALUATE ===",
        output,
    ]

    if context:
        prompt_parts.extend([
            "",
            "=== CONTEXT ===",
            json.dumps(context, indent=2, default=str),
        ])

    prompt_parts.extend([
        "",
        "Evaluate the output above against the rubric. Return ONLY valid JSON.",
        "Do NOT wrap in markdown code fences. Return raw JSON only.",
    ])

    prompt = "\n".join(prompt_parts)

    # Execute judge via claude CLI
    try:
        raw_response = _execute_claude(prompt, model=model)
    except (RuntimeError, TimeoutError) as e:
        return JudgeResult(
            rubric_name=rubric_name,
            dimensions={},
            weights=weights,
            overall_score=0.0,
            weaknesses=[],
            anti_patterns_found=anti_patterns,
            penalty=penalty,
            raw_response="",
            model=model,
            error=str(e),
            duration_ms=int((monotonic() - t0) * 1000),
        )

    # Parse the judge's response
    result = _parse_judge_response(raw_response, weights)
    result.rubric_name = rubric_name
    result.model = model
    result.raw_response = raw_response
    result.anti_patterns_found = anti_patterns
    result.penalty = penalty

    # Apply anti-pattern penalty to overall score
    result.overall_score = max(0.0, result.overall_score - penalty)
    result.overall_score = round(result.overall_score, 3)

    # Enforce weakness requirement for high scores
    if result.overall_score >= 0.8 and len(result.weaknesses) < 1:
        result.weaknesses.append(
            "[Auto-added] Judge failed to identify weaknesses for a high-scoring output. "
            "This itself may indicate evaluation quality issues."
        )

    result.duration_ms = int((monotonic() - t0) * 1000)
    return result


def batch_judge(
    outputs: list[dict],
    rubric_path: str | Path,
    model: str | None = None,
) -> list[JudgeResult]:
    """Judge multiple outputs sequentially.

    Each dict in outputs should have:
        - 'output': str — the text to evaluate
        - 'context': dict (optional) — additional context for the judge
    """
    model = model or "claude-sonnet-4-20250514"
    results = []

    for item in outputs:
        output_text = item.get("output", "")
        context = item.get("context")
        result = judge(output_text, rubric_path, context=context, model=model)
        results.append(result)

    return results


def calibration_check(
    human_scores: list[float],
    judge_scores: list[float],
) -> dict:
    """Compute Spearman rank correlation between human and judge scores.

    Implemented from scratch (no scipy dependency).

    Returns:
        {
            "rho": float,
            "p_value": float,
            "calibrated": bool,       # rho >= 0.7
            "bias_direction": str,     # "lenient" | "strict" | "neutral"
            "bias_magnitude": float,
        }
    """
    n = len(human_scores)
    if n != len(judge_scores):
        raise ValueError(
            f"Score lists must be same length: {n} vs {len(judge_scores)}"
        )
    if n < 3:
        return {
            "rho": 0.0,
            "p_value": 1.0,
            "calibrated": False,
            "bias_direction": "neutral",
            "bias_magnitude": 0.0,
            "n": n,
            "error": "Need at least 3 paired scores for correlation",
        }

    # Compute ranks (average rank for ties)
    human_ranks = _compute_ranks(human_scores)
    judge_ranks = _compute_ranks(judge_scores)

    # Spearman rho = Pearson correlation of ranks
    rho = _pearson(human_ranks, judge_ranks)

    # Approximate p-value using t-distribution approximation
    # t = rho * sqrt((n-2) / (1 - rho^2))
    if abs(rho) >= 1.0:
        p_value = 0.0
    else:
        t_stat = rho * math.sqrt((n - 2) / (1.0 - rho * rho))
        # Two-tailed p-value approximation using the t-distribution
        # For large n, t ~ N(0,1); for small n this is approximate
        p_value = _t_to_p(t_stat, n - 2)

    # Bias: are judge scores systematically higher or lower?
    mean_diff = sum(j - h for j, h in zip(judge_scores, human_scores)) / n
    bias_magnitude = abs(mean_diff)

    if mean_diff > 0.05:
        bias_direction = "lenient"
    elif mean_diff < -0.05:
        bias_direction = "strict"
    else:
        bias_direction = "neutral"

    return {
        "rho": round(rho, 4),
        "p_value": round(p_value, 6),
        "calibrated": rho >= 0.7,
        "bias_direction": bias_direction,
        "bias_magnitude": round(bias_magnitude, 4),
        "n": n,
    }


# --------------------------------------------------------------------------
# Internal: Claude CLI execution
# --------------------------------------------------------------------------

def _execute_claude(
    prompt: str,
    model: str | None = None,
    timeout: int = 120,
) -> str:
    """Run claude --print and return response text.

    Uses --output-format json to get structured output from the CLI.
    Falls back to raw text if JSON parsing fails.
    """
    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "-p", prompt,
    ]

    if model:
        cmd.extend(["--model", model])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude CLI not found. Install with: npm install -g @anthropic/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(
            f"claude --print timed out after {timeout}s"
        )

    if proc.returncode != 0:
        stderr = proc.stderr.strip()[:500] if proc.stderr else "unknown error"
        raise RuntimeError(f"claude CLI failed (exit {proc.returncode}): {stderr}")

    # Try to parse JSON envelope from --output-format json
    try:
        envelope = json.loads(proc.stdout)
        # The CLI returns {"result": "...", "session_id": "...", ...}
        return envelope.get("result", proc.stdout)
    except (json.JSONDecodeError, AttributeError):
        # Fallback: return raw stdout
        return proc.stdout


# --------------------------------------------------------------------------
# Internal: Response parsing
# --------------------------------------------------------------------------

def _parse_judge_response(raw: str, rubric_weights: dict) -> JudgeResult:
    """Parse judge's JSON response into JudgeResult.

    Expected response format:
        {
            "completeness": 0.85,
            "evidence": 0.70,
            ...,
            "weaknesses": ["weakness 1", ...],
            "anti_patterns": ["pattern 1", ...],
            "overall": 0.78
        }

    We recompute overall using weights — don't trust the judge's
    self-reported overall score.
    """
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag)
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        # Remove closing fence
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON from mixed text
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                return _error_judge_result(
                    error=f"Could not parse JSON from judge response: {raw[:200]}",
                    weights=rubric_weights,
                )
        else:
            return _error_judge_result(
                error=f"No JSON found in judge response: {raw[:200]}",
                weights=rubric_weights,
            )

    # Extract dimension scores
    dimensions: dict[str, float] = {}
    for dim_key in rubric_weights:
        # Try exact match, then common abbreviations
        val = data.get(dim_key)
        if val is None:
            # Try without underscores (e.g., "intellectual_courage" -> check variations)
            for data_key in data:
                if isinstance(data.get(data_key), (int, float)):
                    normalized = data_key.lower().replace(" ", "_").replace("-", "_")
                    if normalized == dim_key:
                        val = data[data_key]
                        break
        if val is not None:
            dimensions[dim_key] = max(0.0, min(1.0, float(val)))
        else:
            dimensions[dim_key] = 0.0  # Missing dimension = 0

    # Extract weaknesses
    weaknesses = data.get("weaknesses", [])
    if isinstance(weaknesses, str):
        weaknesses = [weaknesses]
    weaknesses = [str(w) for w in weaknesses if w]

    # Extract anti-patterns reported by judge (separate from our detection)
    judge_anti_patterns = data.get("anti_patterns", [])
    if isinstance(judge_anti_patterns, str):
        judge_anti_patterns = [judge_anti_patterns]

    # Recompute overall from weights — do NOT trust judge's self-reported overall
    overall = 0.0
    for dim_key, weight in rubric_weights.items():
        overall += dimensions.get(dim_key, 0.0) * weight

    return JudgeResult(
        rubric_name="",  # Filled by caller
        dimensions=dimensions,
        weights=rubric_weights,
        overall_score=round(overall, 3),
        weaknesses=weaknesses,
        anti_patterns_found=list(judge_anti_patterns),
        penalty=0.0,  # Filled by caller after anti-pattern detection
        raw_response=raw,
        model="",  # Filled by caller
    )


def _error_judge_result(error: str, weights: dict) -> JudgeResult:
    """Create an error JudgeResult when parsing fails."""
    return JudgeResult(
        rubric_name="",
        dimensions={dim: 0.0 for dim in weights},
        weights=weights,
        overall_score=0.0,
        weaknesses=[],
        anti_patterns_found=[],
        penalty=0.0,
        raw_response="",
        model="",
        error=error,
    )


# --------------------------------------------------------------------------
# Internal: Anti-pattern detection
# --------------------------------------------------------------------------

def _detect_anti_patterns(output: str) -> tuple[list[str], float]:
    """Detect anti-patterns in the original output (not the judge response).

    Returns (list of found patterns, total penalty).

    Patterns and penalties:
    - Sycophantic opening: -0.10
    - Motivational language: -0.10
    - Excessive hedging (>3 instances): -0.05
    - Excessive length without substance (>2000 words, <4 headings): -0.10
    """
    found: list[str] = []
    total_penalty = 0.0

    # Check first 200 chars for sycophantic opener
    opener = output[:200] if output else ""
    if _SYCOPHANTIC_OPENERS.search(opener):
        found.append("Sycophantic opening")
        total_penalty += 0.10

    # Motivational language anywhere
    if _MOTIVATIONAL_LANGUAGE.search(output):
        found.append("Motivational language instead of factual")
        total_penalty += 0.10

    # Excessive hedging
    hedge_count = len(_HEDGE_WORDS.findall(output))
    if hedge_count > 3:
        found.append(f"Excessive hedging ({hedge_count} instances)")
        total_penalty += 0.05

    # Excessive length without proportional substance
    word_count = len(output.split())
    heading_count = len(re.findall(r"^#{1,6}\s+", output, re.MULTILINE))
    if word_count > 2000 and heading_count < 4:
        found.append(
            f"Excessive length ({word_count} words) without proportional "
            f"structure ({heading_count} headings)"
        )
        total_penalty += 0.10

    return found, round(total_penalty, 2)


# --------------------------------------------------------------------------
# Internal: Statistics (Spearman from scratch)
# --------------------------------------------------------------------------

def _compute_ranks(values: list[float]) -> list[float]:
    """Convert values to average ranks (handles ties)."""
    n = len(values)
    # Pair each value with its original index
    indexed = sorted(enumerate(values), key=lambda x: x[1])

    ranks = [0.0] * n
    i = 0
    while i < n:
        # Find the extent of tied values
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1

        # Average rank for all tied values (1-based ranks)
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            original_idx = indexed[k][0]
            ranks[original_idx] = avg_rank

        i = j

    return ranks


def _pearson(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation coefficient."""
    n = len(x)
    if n == 0:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)

    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        return 0.0

    return cov / denom


def _t_to_p(t_stat: float, df: int) -> float:
    """Approximate two-tailed p-value from t-statistic and degrees of freedom.

    Uses the approximation: p ~ 2 * (1 - Phi(|t| * sqrt(df / (df + t^2))))
    where Phi is the standard normal CDF, which works reasonably well
    for df >= 3.
    """
    if df <= 0:
        return 1.0

    # For large df, t-distribution approaches normal
    # Use the approximation from Abramowitz & Stegun
    abs_t = abs(t_stat)

    # Transform to approximate normal z
    # z ~ t * (1 - 1/(4*df)) / sqrt(1 + t^2/(2*df))
    z = abs_t * (1.0 - 1.0 / (4.0 * df)) / math.sqrt(1.0 + (abs_t ** 2) / (2.0 * df))

    # Standard normal CDF approximation (Abramowitz & Stegun 26.2.17)
    p_one_tail = _norm_sf(z)

    return min(2.0 * p_one_tail, 1.0)


def _norm_sf(z: float) -> float:
    """Survival function (1 - CDF) for standard normal distribution.

    Uses Abramowitz & Stegun approximation 26.2.17 (max error 7.5e-8).
    """
    if z < 0:
        return 1.0 - _norm_sf(-z)

    # Constants for the approximation
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    p = 0.2316419

    t = 1.0 / (1.0 + p * z)
    t2 = t * t
    t3 = t2 * t
    t4 = t3 * t
    t5 = t4 * t

    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return phi * (b1 * t + b2 * t2 + b3 * t3 + b4 * t4 + b5 * t5)


# --------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="LLM-as-Judge evaluator")
    parser.add_argument("--output", type=str, help="File containing output to judge")
    parser.add_argument("--output-text", type=str, help="Raw text to judge (alternative to --output)")
    parser.add_argument("--rubric", type=str, required=True, help="Path to rubric markdown file")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514", help="Judge model")
    parser.add_argument("--context-json", type=str, help="Optional JSON context string")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")

    args = parser.parse_args()

    # Load output text
    if args.output:
        output_text = Path(args.output).expanduser().read_text(encoding="utf-8")
    elif args.output_text:
        output_text = args.output_text
    else:
        parser.error("Provide either --output (file) or --output-text (string)")
        return

    # Parse optional context
    context = None
    if args.context_json:
        try:
            context = json.loads(args.context_json)
        except json.JSONDecodeError:
            print(f"Warning: could not parse --context-json, ignoring")

    result = judge(output_text, args.rubric, context=context, model=args.model)

    # Print scorecard
    print(f"\n{'=' * 60}")
    print(f"  EVAL SCORECARD: {result.rubric_name}")
    print(f"{'=' * 60}")

    if result.error:
        print(f"\n  ERROR: {result.error}")
        return

    print(f"\n  {'Dimension':<25} {'Score':>7}  {'Status':<8}")
    print(f"  {'-' * 25} {'-' * 7}  {'-' * 8}")

    for dim, score in result.dimensions.items():
        weight = result.weights.get(dim, 0)
        status = "GREEN" if score >= 0.8 else ("YELLOW" if score >= 0.6 else "RED")
        dim_label = f"{dim} ({weight:.0%})"
        print(f"  {dim_label:<25} {score:>7.2f}  {status:<8}")

    print(f"  {'-' * 25} {'-' * 7}  {'-' * 8}")

    if result.penalty > 0:
        print(f"  {'Anti-pattern penalty':<25} {-result.penalty:>+7.2f}")

    overall_status = "GREEN" if result.overall_score >= 0.8 else (
        "YELLOW" if result.overall_score >= 0.6 else "RED"
    )
    print(f"  {'OVERALL':<25} {result.overall_score:>7.2f}  {overall_status:<8}")

    if result.weaknesses:
        print(f"\n  Weaknesses:")
        for i, w in enumerate(result.weaknesses, 1):
            print(f"    {i}. {w}")

    if result.anti_patterns_found:
        print(f"\n  Anti-Patterns Detected:")
        for ap in result.anti_patterns_found:
            print(f"    - {ap}")

    print(f"\n  Model: {result.model}")
    print(f"  Duration: {result.duration_ms}ms")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
