# Extractor comparison against manual ground truth

System `geoserver-cloud` @ `70cf0825`. Ground truth: **7 inbound endpoints**, **0 outbound calls**, labeled manually by Jaroslav Knapek on 2026-09-09 (7/718 files read in full).

Matching levels are defined in `groundtruth/README.md` section 5. M2 is the operative level; M1 measures notation compatibility, not detection.

## Inbound endpoints — F1 per matching level

| extractor | found | M1 exact | M2 normalized | M3 path only | M4 code |
|---|---:|---:|---:|---:|---:|
| CIMET | 3 | 0.400 | 0.400 | 0.400 | 0.600 |
| LLM gemini-3.5-flash-lite per-file | 7 | 0.714 | 1.000 | 1.000 | 1.000 |
| LLM gpt-oss-120b per-file | 12 | 0.632 | 0.632 | 0.737 | 0.737 |
| LLM spark-x2.5-4b agent (effort none) | 5 | 0.500 | 0.833 | 0.833 | 0.833 |

## Inbound endpoints — precision / recall at M2

| extractor | tp | fp | fn | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| CIMET | 2 | 1 | 5 | 0.667 | 0.286 | 0.400 |
| LLM gemini-3.5-flash-lite per-file | 7 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| LLM gpt-oss-120b per-file | 6 | 6 | 1 | 0.500 | 0.857 | 0.632 |
| LLM spark-x2.5-4b agent (effort none) | 5 | 0 | 2 | 1.000 | 0.714 | 0.833 |

## Error decomposition

| extractor | missed | role-separation errors | hallucinations | duplicates |
|---|---:|---:|---:|---:|
| CIMET | 5 | 0 | 0 | 0 |
| LLM gemini-3.5-flash-lite per-file | 0 | 0 | 0 | 0 |
| LLM gpt-oss-120b per-file | 1 | 0 | 5 | 0 |
| LLM spark-x2.5-4b agent (effort none) | 2 | 0 | 0 | 0 |

## Outbound calls

| extractor | emits outbound? | M2 F1 |
|---|---|---:|
| CIMET | no | — |
| LLM gemini-3.5-flash-lite per-file | no | — |
| LLM gpt-oss-120b per-file | no | — |
| LLM spark-x2.5-4b agent (effort none) | no | — |

## Cost and runtime

Per-file: one request per file. Agent: one request per step. Correct = inbound true positives at M2. Local models have no list price.

| extractor | files ok / requests | tokens in / out | wall | s per request | list price | correct | tokens per correct | $ per correct |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| CIMET | deterministic | – | not measured | – | $0 | 2 | – | – |
| LLM gemini-3.5-flash-lite per-file | 712/712 files | 912,862 / 56,117 | 2746.0 s | 3.9 | $0.1137 | 7 | 138,425 | $0.0162 |
| LLM gpt-oss-120b per-file | 703/712 files | 760,499 / 104,289 | 3927.0 s | 5.5 | $0.1766 | 6 | 144,131 | $0.0294 |
| LLM spark-x2.5-4b agent (effort none) | 14 steps | 53,327 / 1,745 | 554.7 s | 39.6 | local | 5 | 11,014 | – |
