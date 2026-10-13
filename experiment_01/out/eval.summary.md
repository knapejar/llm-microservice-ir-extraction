# Extractor comparison against manual ground truth

System `spring-cloud-movie-recommendation` @ `5aa5ee9e`. Ground truth: **14 inbound endpoints**, **9 outbound calls**, labeled manually by Jaroslav Knapek on 2026-09-09 (31/31 files read in full).

Matching levels are defined in `groundtruth/README.md` section 5. M2 is the operative level; M1 measures notation compatibility, not detection.

## Inbound endpoints — F1 per matching level

| extractor | found | M1 exact | M2 normalized | M3 path only | M4 code |
|---|---:|---:|---:|---:|---:|
| CIMET | 14 | 0.500 | 1.000 | 1.000 | 1.000 |
| LLM gemini-2.5-flash-lite per-file | 23 | 0.757 | 0.757 | 0.757 | 0.757 |
| LLM gemini-3.5-flash-lite per-file | 14 | 1.000 | 1.000 | 1.000 | 1.000 |
| LLM gpt-oss-120b per-file | 14 | 1.000 | 1.000 | 1.000 | 1.000 |
| LLM spark-x2.5-4b per-file (effort none) | 25 | 0.718 | 0.718 | 0.718 | 0.718 |
| LLM spark-x2.5-4b agent (effort none) | 14 | 1.000 | 1.000 | 1.000 | 1.000 |
| LLM spark-x2.5-4b agent (effort low) | 14 | 1.000 | 1.000 | 1.000 | 1.000 |

## Inbound endpoints — precision / recall at M2

| extractor | tp | fp | fn | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| CIMET | 14 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| LLM gemini-2.5-flash-lite per-file | 14 | 9 | 0 | 0.609 | 1.000 | 0.757 |
| LLM gemini-3.5-flash-lite per-file | 14 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| LLM gpt-oss-120b per-file | 14 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| LLM spark-x2.5-4b per-file (effort none) | 14 | 11 | 0 | 0.560 | 1.000 | 0.718 |
| LLM spark-x2.5-4b agent (effort none) | 14 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| LLM spark-x2.5-4b agent (effort low) | 14 | 0 | 0 | 1.000 | 1.000 | 1.000 |

## Error decomposition

| extractor | missed | role-separation errors | hallucinations | duplicates |
|---|---:|---:|---:|---:|
| CIMET | 0 | 0 | 0 | 0 |
| LLM gemini-2.5-flash-lite per-file | 0 | 9 | 0 | 1 |
| LLM gemini-3.5-flash-lite per-file | 0 | 0 | 0 | 0 |
| LLM gpt-oss-120b per-file | 0 | 0 | 0 | 0 |
| LLM spark-x2.5-4b per-file (effort none) | 0 | 9 | 2 | 1 |
| LLM spark-x2.5-4b agent (effort none) | 0 | 0 | 0 | 0 |
| LLM spark-x2.5-4b agent (effort low) | 0 | 0 | 0 | 0 |

## Outbound calls

| extractor | emits outbound? | M2 F1 |
|---|---|---:|
| CIMET | yes (9) | 1.000 |
| LLM gemini-2.5-flash-lite per-file | no | — |
| LLM gemini-3.5-flash-lite per-file | no | — |
| LLM gpt-oss-120b per-file | no | — |
| LLM spark-x2.5-4b per-file (effort none) | no | — |
| LLM spark-x2.5-4b agent (effort none) | no | — |
| LLM spark-x2.5-4b agent (effort low) | no | — |

## Cost and runtime

Per-file: one request per file. Agent: one request per step. Correct = inbound true positives at M2. Local models have no list price.

| extractor | files ok / requests | tokens in / out | wall | s per request | list price | correct | tokens per correct | $ per correct |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| CIMET | deterministic | – | not measured | – | $0 | 14 | – | – |
| LLM gemini-2.5-flash-lite per-file | 31/31 files | 17,608 / 3,978 | 32.1 s | 1.0 | $0.0034 | 14 | 1,541 | $0.0002 |
| LLM gemini-3.5-flash-lite per-file | 31/31 files | 17,608 / 3,174 | 34.3 s | 1.1 | $0.003 | 14 | 1,484 | $0.0002 |
| LLM gpt-oss-120b per-file | 31/31 files | 16,798 / 6,028 | 33.1 s | 1.1 | $0.0061 | 14 | 1,630 | $0.0004 |
| LLM spark-x2.5-4b per-file (effort none) | 31/31 files | 17,813 / 4,521 | 246.7 s | 8.0 | local | 14 | 1,595 | – |
| LLM spark-x2.5-4b agent (effort none) | 7 steps | 16,406 / 1,647 | 121.8 s | 17.4 | local | 14 | 1,289 | – |
| LLM spark-x2.5-4b agent (effort low) | 13 steps | 48,827 / 11,397 | 348.4 s | 26.8 | local | 14 | 4,301 | – |
