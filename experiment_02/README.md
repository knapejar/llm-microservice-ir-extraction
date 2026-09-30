# Experiment 02: agentic extraction

Same task and output schema as experiment_01, but the model explores the
repository itself with read-only tools (`list_dir`, `grep`, `read_file`) and
submits one validated document at the end.

Guards: older tool results are dropped when the context fills up, API errors
are retried, repeating the same call three times triggers a warning and then a
forced submit, and a run always writes an output (`_run` records whether it
was accepted).

## Run

```bash
python agent_extract.py --repo <checkout> --system-name <system> --effort none
python test_loop_guard.py <checkout of spring-cloud-movie-recommendation>
```

Default model: `spark-x2.5-4b` in LM Studio, temperature 0, 60 steps. Score
with `../experiment_01/evaluate.py` or open `../experiment_01/out/viewer.html`.

## Results (movie, inbound, M2)

| workflow | model | F1 | false positives | wall |
|---|---|---:|---:|---:|
| per-file | spark-x2.5-4b | 0.718 | 11 | 247 s |
| agent, effort none | spark-x2.5-4b | 1.000 | 0 | 122 s |
| agent, effort low | spark-x2.5-4b | 1.000 | 0 | 348 s |

Same model: exploring the repository removes the Feign client methods that the
per-file workflow reports as inbound endpoints.
