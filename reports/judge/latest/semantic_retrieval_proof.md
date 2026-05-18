# AccessLab Semantic Retrieval Proof

- Generated at: 2026-05-18T19:14:07.983699+00:00
- Runtime backend: ollama
- Deployment mode: single-user-local
- Model tier: E4B
- Semantic model: embeddinggemma
- Semantic status: Ready (ok)
- Semantic retrieval ready: True
- Question: How do I combine the numbers?
- Expected evidence substring: `add the values together to get the final total`

## Retrieval Modes

| Requested | Effective | Top chunk | Top source | Top expected | Any expected | Results |
| --- | --- | --- | --- | --- | --- | --- |
| lexical | Lexical only | retrieval_smoke_distractor-p0-c1-e5826125ae | retrieval_smoke_distractor.md | False | True | 2 |
| semantic | Semantic only | retrieval_smoke_relevant-p0-c1-e3bfdd5c71 | retrieval_smoke_relevant.md | True | True | 2 |
| hybrid | Hybrid | retrieval_smoke_relevant-p0-c1-e3bfdd5c71 | retrieval_smoke_relevant.md | True | True | 2 |

## Comparison Summary

- Hybrid improved expected-evidence support over lexical: True
- Semantic changed retrieved chunks versus lexical: True
- Hybrid changed retrieved chunks versus lexical: True
- Semantic neutral or failed: False
- Overall result: pass

## Honest Limits

- This proof measures retrieval ranking over a small local fixture, not answer quality by itself.
- Hybrid may be neutral when lexical already retrieves the strongest evidence.
- Semantic-only is useful as a diagnostic, not the default product path.
- If EmbeddingGemma is unavailable, AccessLab must report lexical fallback instead of claiming hybrid retrieval.

## Lexical Results

1. `retrieval_smoke_distractor-p0-c1-e5826125ae` from `retrieval_smoke_distractor.md` (match=lexical)
   [The] worksheet lists [the] [numbers] beside question 3 so students can copy them.

2. `retrieval_smoke_relevant-p0-c1-e3bfdd5c71` from `retrieval_smoke_relevant.md` (match=lexical)
   Add [the] values together to get [the] final total for [the] answer.

## Semantic Results

1. `retrieval_smoke_relevant-p0-c1-e3bfdd5c71` from `retrieval_smoke_relevant.md` (match=semantic, semantic_similarity=0.4060)
   Add the values together to get the final total for the answer.

2. `retrieval_smoke_distractor-p0-c1-e5826125ae` from `retrieval_smoke_distractor.md` (match=semantic, semantic_similarity=0.2226)
   The worksheet lists the numbers beside question 3 so students can copy them.

## Hybrid Results

1. `retrieval_smoke_relevant-p0-c1-e3bfdd5c71` from `retrieval_smoke_relevant.md` (match=hybrid, semantic_similarity=0.4060)
   Add [the] values together to get [the] final total for [the] answer.

2. `retrieval_smoke_distractor-p0-c1-e5826125ae` from `retrieval_smoke_distractor.md` (match=hybrid, semantic_similarity=0.2226)
   [The] worksheet lists [the] [numbers] beside question 3 so students can copy them.
