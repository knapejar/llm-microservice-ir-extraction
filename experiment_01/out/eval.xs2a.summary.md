# Extractor comparison against manual ground truth

System `xs2a` @ `2603384e`. Ground truth: **50 inbound endpoints**, **0 outbound calls**, labeled manually by Jaroslav Knapek on 2026-09-09.

Matching levels are defined in `groundtruth/README.md` section 5. M2 is the operative level; M1 measures notation compatibility, not detection.

## Inbound endpoints — F1 per matching level

| extractor | found | M1 exact | M2 normalized | M3 path only | M4 code |
|---|---:|---:|---:|---:|---:|
| CIMET | 0 | n/a | n/a | n/a | n/a |
| LLM gemini-3.5-flash-lite per-file | 50 | 1.000 | 1.000 | 1.000 | 1.000 |
| LLM gpt-oss-120b per-file | 2 | 0.077 | 0.077 | 0.077 | 0.077 |

## Inbound endpoints — precision / recall at M2

| extractor | tp | fp | fn | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| CIMET | 0 | 0 | 50 | n/a | 0.000 | n/a |
| LLM gemini-3.5-flash-lite per-file | 50 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| LLM gpt-oss-120b per-file | 2 | 0 | 48 | 1.000 | 0.040 | 0.077 |

## Error decomposition

| extractor | missed | role-separation errors | hallucinations | duplicates |
|---|---:|---:|---:|---:|
| CIMET | 50 | 0 | 0 | 0 |
| LLM gemini-3.5-flash-lite per-file | 0 | 0 | 0 | 2 |
| LLM gpt-oss-120b per-file | 48 | 0 | 0 | 0 |

## Outbound calls

| extractor | emits outbound? | M2 F1 |
|---|---|---:|
| CIMET | no | — |
| LLM gemini-3.5-flash-lite per-file | no | — |
| LLM gpt-oss-120b per-file | no | — |

## Cost and runtime

| extractor | schema valid | wall | list-price cost |
|---|---|---:|---:|
| CIMET | n/a (deterministic) | not measured | $0 |
| LLM gemini-3.5-flash-lite per-file | 294/294 | 1521.7 s | $0.0807 |
| LLM gpt-oss-120b per-file | 285/294 | 657.0 s | $0.0948 |
