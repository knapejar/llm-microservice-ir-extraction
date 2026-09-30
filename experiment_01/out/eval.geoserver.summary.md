# Extractor comparison against manual ground truth

System `geoserver-cloud` @ `70cf0825`. Ground truth: **7 inbound endpoints**, **0 outbound calls**, labeled manually by Jaroslav Knapek on 2026-09-09 (7/718 files read in full).

Matching levels are defined in `groundtruth/README.md` section 5. M2 is the operative level; M1 measures notation compatibility, not detection.

## Inbound endpoints — F1 per matching level

| extractor | found | M1 exact | M2 normalized | M3 path only | M4 code |
|---|---:|---:|---:|---:|---:|
| CIMET | 3 | 0.400 | 0.400 | 0.400 | 0.600 |
| LLM gemini-3.5-flash-lite per-file | 7 | 0.714 | 1.000 | 1.000 | 1.000 |

## Inbound endpoints — precision / recall at M2

| extractor | tp | fp | fn | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| CIMET | 2 | 1 | 5 | 0.667 | 0.286 | 0.400 |
| LLM gemini-3.5-flash-lite per-file | 7 | 0 | 0 | 1.000 | 1.000 | 1.000 |

## Error decomposition

| extractor | missed | role-separation errors | hallucinations | duplicates |
|---|---:|---:|---:|---:|
| CIMET | 5 | 0 | 0 | 0 |
| LLM gemini-3.5-flash-lite per-file | 0 | 0 | 0 | 0 |

## Outbound calls

| extractor | emits outbound? | M2 F1 |
|---|---|---:|
| CIMET | no | — |
| LLM gemini-3.5-flash-lite per-file | no | — |

## Cost and runtime

| extractor | schema valid | wall | list-price cost |
|---|---|---:|---:|
| CIMET | n/a (deterministic) | not measured | $0 |
| LLM gemini-3.5-flash-lite per-file | 712/712 | 2746.0 s | $0.1137 |
