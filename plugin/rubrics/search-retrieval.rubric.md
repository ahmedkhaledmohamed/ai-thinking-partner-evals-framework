# Search & Retrieval Evaluation Rubric

You are evaluating an AI-generated search or RAG (Retrieval-Augmented Generation) output — a response that synthesizes information from retrieved sources (documents, code, knowledge bases). The standard is: can the reader trust the citations and act on the synthesis?

Rate each dimension 0.0-1.0:

## Citation Accuracy (weight: 0.35)
- 1.0: Every cited source actually says what was claimed. Quotes are verbatim or faithful paraphrases. No misattributions. No phantom citations (sources that don't exist or weren't retrieved).
- 0.7: Most citations are accurate, but 1-2 are imprecise paraphrases that slightly distort the source's meaning.
- 0.4: Several citations are misleading — the source exists but doesn't actually support the claim made. Or citations are so vague ("as mentioned in the docs") that they can't be verified.
- 0.0: Fabricated citations. References documents that don't exist. Makes claims and attributes them to sources that say something different.

THIS IS THE HIGHEST-WEIGHTED DIMENSION. Citation fabrication is the most dangerous failure mode in RAG systems. Check for:
- Does the cited document actually contain the claimed information?
- Are numbers attributed to a source actually in that source?
- Are quotes accurate, or subtly modified to support the narrative?
- Are "source not found" situations handled honestly?

## Relevance (weight: 0.25)
- 1.0: The response directly answers the question asked. Top results are the most relevant available. No tangential information padding the answer.
- 0.7: Answer is relevant, but includes some tangential information that doesn't help answer the question. Core answer is present but buried.
- 0.4: Partially relevant — addresses the topic area but not the specific question. Returns information about the right system but wrong aspect.
- 0.0: Off-topic. Retrieved sources don't relate to the question.

Check for: Does the answer address the user's actual question, or a related-but-different question? Is the most important information surfaced first? Is there padding with marginally relevant details?

## Completeness (weight: 0.20)
- 1.0: Doesn't miss obvious relevant sources. If there are 5 documents about the topic, all 5 are surfaced (or the omission is noted). Cross-references between sources are identified.
- 0.7: Covers the main sources, but misses 1-2 relevant documents that would have added important context.
- 0.4: Only finds the most obvious source, missing others that would significantly change the answer.
- 0.0: Misses the most relevant source entirely. Answers from peripheral documents while the authoritative source exists and was available.

Check for: Are there known documents about this topic that weren't retrieved? Does the answer acknowledge when the corpus might be incomplete? Are contradicting sources surfaced rather than hidden?

## Source Diversity (weight: 0.20)
- 1.0: Uses multiple source types (docs, code, Slack threads, Confluence, GDrive) when available. Triangulates claims across independent sources. Notes when sources agree or disagree.
- 0.7: Uses 2-3 source types. Doesn't over-rely on a single document.
- 0.4: All information comes from a single source or source type, even when others are available.
- 0.0: Single-source answer presented as comprehensive. No attempt to cross-reference.

Check for: If the answer cites 5 sources, are they truly independent or just different sections of the same document? Does it triangulate (e.g., code confirms what the doc says)? Does it note when sources are all from the same author or time period?

## Anti-Patterns (penalize by 0.1 each)
- Phantom citations: Referencing a source that doesn't exist or wasn't in the retrieval results
- Cherry-picking: Citing only sources that support one interpretation while ignoring contradicting ones
- Recency bias: Using only the newest source when older authoritative sources are more accurate
- Confidence without coverage: Answering definitively when the corpus only partially covers the topic
- Source laundering: Citing a secondary source that itself cites the primary, losing fidelity

## Output Format
Return ONLY valid JSON (no markdown fences, no explanation):
{"citation_accuracy": 0.0-1.0, "relevance": 0.0-1.0, "completeness": 0.0-1.0, "source_diversity": 0.0-1.0, "weaknesses": ["specific weakness 1", "specific weakness 2"], "anti_patterns": ["pattern found if any"], "overall": 0.0-1.0}

IMPORTANT: You MUST list at least one weakness. Even strong retrieval outputs can improve on source diversity or completeness caveats.
