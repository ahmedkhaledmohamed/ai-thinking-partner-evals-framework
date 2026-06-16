# Code & Technical Analysis Evaluation Rubric

You are evaluating AI-generated code or a technical analysis (architecture explanation, code review, system investigation). The standard is: would a senior engineer on the team accept this without significant rework?

Rate each dimension 0.0-1.0:

## Correctness (weight: 0.30)
- 1.0: Code compiles/runs, handles edge cases, technical explanations are accurate and match the actual system behavior. No logical errors.
- 0.7: Core logic is correct, but 1-2 minor issues (missing null check, off-by-one, incomplete error handling). Technical explanations are mostly accurate with minor imprecisions.
- 0.4: Fundamental logic errors or technical misunderstandings that would cause bugs in production. Explanation describes something different from what the code does.
- 0.0: Code would not compile/run. Technical explanation is wrong about how the system works.

For code: Would it pass code review? For explanations: Would someone who knows the system confirm the description?

## Pattern Conformance (weight: 0.20)
- 1.0: Follows existing codebase patterns — same error handling approach, same naming conventions, same architectural layers, same test structure. Looks like it belongs in the repo.
- 0.7: Generally follows patterns, but introduces one new abstraction or convention without justification.
- 0.4: Invents new patterns when existing ones would work. Inconsistent style with the surrounding code.
- 0.0: Ignores codebase conventions entirely. Looks like it was written for a different project.

Check for: Does it use the same framework patterns (Apollo for backend, Mobius for client)? Same dependency injection approach? Same logging/metrics style? Same test framework (JUnit 5 not 4, proper TestContainers usage)? If the codebase uses gRPC, does the code use gRPC?

## Minimality (weight: 0.20)
- 1.0: Minimal diff for the problem scope. No unnecessary refactoring, no extra features, no "while I'm here" changes. Does exactly what was asked.
- 0.7: Mostly focused, but includes 1-2 nice-to-have changes that weren't requested.
- 0.4: Significant scope creep — refactors adjacent code, adds features not requested, introduces abstractions "for future use".
- 0.0: Complete rewrite when a targeted fix would suffice. Or adds entire new modules for a one-line problem.

Red flags: New abstract base classes for a single implementation. Configuration options nobody asked for. "I also improved X while I was at it." Helper utilities that are used exactly once.

## Security (weight: 0.15)
- 1.0: No injection vulnerabilities, no hardcoded secrets, proper input validation, safe patterns for the technology (parameterized queries, escaped outputs, etc.).
- 0.7: Generally secure, but missing one defense-in-depth measure (e.g., input validation present but no output encoding).
- 0.4: Contains a vulnerability that would be caught in security review (e.g., string concatenation in SQL, unsanitized user input in templates).
- 0.0: Hardcoded credentials, obvious injection vectors, or disabling security features.

Check for: Hardcoded API keys or tokens, SQL injection via string formatting, unsanitized user input, overly permissive file operations, disabled SSL verification, use of eval() or equivalent.

## Explanation Accuracy (weight: 0.15)
- 1.0: Technical explanations match exactly what the code does. Cause-and-effect chains are correct. System interactions described match the actual protocol/API.
- 0.7: Explanations are correct in substance, but imprecise on 1-2 details (e.g., says "REST" when it's actually gRPC, or describes the flow in slightly wrong order).
- 0.4: Explanations describe the general area but get specific mechanisms wrong. Would mislead someone trying to debug the system.
- 0.0: Explanations contradict what the code actually does. Describes a system that doesn't exist.

For code changes: Does the PR description accurately describe what the code does? For technical analysis: Would reading only the explanation give you a correct mental model of the system?

## Anti-Patterns (penalize by 0.1 each)
- Over-engineering: Abstract factory for a single concrete type, strategy pattern for one strategy
- Cargo-cult patterns: Using design patterns because they're "best practice" without a concrete need
- Premature optimization: Complex caching or batching for a path that handles 10 requests/day
- Dead code: Commented-out code, unused imports, placeholder TODOs that will never be addressed
- Wrong abstraction level: Explaining implementation details when asked about architecture, or vice versa

## Output Format
Return ONLY valid JSON (no markdown fences, no explanation):
{"correctness": 0.0-1.0, "pattern_conformance": 0.0-1.0, "minimality": 0.0-1.0, "security": 0.0-1.0, "explanation_accuracy": 0.0-1.0, "weaknesses": ["specific weakness 1", "specific weakness 2"], "anti_patterns": ["pattern found if any"], "overall": 0.0-1.0}

IMPORTANT: You MUST list at least one weakness. Even good code has room for improvement — identify what a thorough reviewer would flag.
