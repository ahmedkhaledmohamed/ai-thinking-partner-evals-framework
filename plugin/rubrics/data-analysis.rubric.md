# Data Analysis Evaluation Rubric

You are evaluating an AI-generated data analysis output — typically a BigQuery analysis with SQL queries, findings, and interpretations. The standard is: would a data-literate PM trust these numbers and act on them?

Rate each dimension 0.0-1.0:

## Query Validity (weight: 0.20)
- 1.0: SQL parses correctly, uses partition filters (e.g., _PARTITIONTIME), joins are appropriate, cost is reasonable (no SELECT * on massive tables without LIMIT or partition filter).
- 0.7: SQL is valid and would run, but missing partition filters or using unnecessarily expensive patterns (cross joins, full table scans).
- 0.4: SQL has minor errors that would cause failures, or uses patterns that would time out on production-scale tables.
- 0.0: SQL is fundamentally broken, references non-existent tables/columns, or would scan petabytes without filters.

Check for: _PARTITIONTIME or _TABLE_SUFFIX filters on date-partitioned tables, appropriate use of GROUP BY, correct JOIN conditions, LIMIT on exploratory queries. If no SQL is present (pre-computed data), evaluate whether the data source and filtering are described clearly enough to reproduce.

## Interpretation Quality (weight: 0.25)
- 1.0: Follows the full chain: Question -> Approach -> Findings -> Interpretation -> Limitations -> Next Steps. Each step is explicit. Findings lead logically to interpretation.
- 0.7: Most steps present. Interpretation follows from data, but one step (usually Limitations or Next Steps) is missing or thin.
- 0.4: Jumps from data to conclusions without explaining the reasoning. Missing intermediate steps.
- 0.0: Conclusions don't follow from the data shown, or no interpretation is offered beyond raw numbers.

Check for: Does the interpretation explain WHY the numbers look the way they do, not just WHAT they are? "Push delivery dropped 3% in March" is a finding. "Push delivery dropped 3% in March, likely driven by the Android 14 API change that affected background processing" is an interpretation.

## Caveat Presence (weight: 0.20)
- 1.0: Limitations explicitly stated — sample size, time window, data freshness, known gaps, survivorship bias, selection effects. Reader knows exactly how much to trust the numbers.
- 0.7: Major limitations mentioned, but some obvious caveats missing (e.g., not mentioning that the data only covers 7 days).
- 0.4: Token caveat ("note: this is based on available data") without specifics.
- 0.0: No caveats. Numbers presented as absolute truth.

Must-have caveats for common analyses:
- Time window: "This covers [date range], which [does/doesn't] include [relevant event]"
- Sample size: How many users/events? Is it representative?
- Data freshness: When was the latest partition? Is there processing lag?
- Known gaps: Are there platforms, markets, or user segments excluded?

## Causal Claim Discipline (weight: 0.15)
- 1.0: Carefully distinguishes correlation from causation. Uses "associated with", "coincided with", "suggests" rather than "caused by", "resulted in", "due to" when the data only shows correlation. If a causal claim is made, it's backed by an experiment or controlled comparison.
- 0.7: Mostly careful, but slips into causal language once or twice without experimental evidence.
- 0.4: Regularly implies causation from observational data ("the feature launch caused a 5% increase" without A/B test data).
- 0.0: Treats all correlations as causal. Makes definitive causal claims from time-series overlaps.

Red flags: "X caused Y" without an experiment. "After we launched X, Y improved" presented as proof of causation. Ignoring confounders.

## Platform Segmentation (weight: 0.20)
- 1.0: Breaks down by iOS/Android (and Desktop when relevant) as standard practice. Never shows combined "all platforms" numbers when the split matters. Highlights platform-specific anomalies.
- 0.7: Platform split shown for key metrics, but some secondary metrics shown combined without justification.
- 0.4: Occasionally mentions platform differences but primarily shows combined numbers.
- 0.0: All numbers are combined across platforms. No platform segmentation attempted.

This matters because: iOS and Android have fundamentally different push delivery mechanisms, app lifecycle behaviors, and permission models. Combined numbers routinely hide platform-specific regressions. Silent vs. visible push must also be split — never show combined "Push (All)".

## Anti-Patterns (penalize by 0.1 each)
- Presenting combined push metrics without silent/visible split
- Using "all platforms" numbers when iOS/Android split would reveal different stories
- Making causal claims from observational data without caveats
- Showing percentages without absolute numbers (or vice versa without context)
- Quoting numbers to false precision (e.g., "12.847% increase" when the confidence interval spans 5 points)

## Output Format
Return ONLY valid JSON (no markdown fences, no explanation):
{"query_validity": 0.0-1.0, "interpretation_quality": 0.0-1.0, "caveat_presence": 0.0-1.0, "causal_claim_discipline": 0.0-1.0, "platform_segmentation": 0.0-1.0, "weaknesses": ["specific weakness 1", "specific weakness 2"], "anti_patterns": ["pattern found if any"], "overall": 0.0-1.0}

IMPORTANT: You MUST list at least one weakness. Data analysis outputs almost always have room for better caveats or deeper segmentation.
