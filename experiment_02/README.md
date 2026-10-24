# Experiment 02: agentic extraction

Same task as experiment_01, but the model explores the repository itself with
read-only tools (`list_dir`, `find`, `grep`, `read_file`). It records services
and inbound endpoints as it finds them (`record`) and ends with `submit`.
Diagrams of the loop and its tools, and a traced example run:
[how-it-works.md](how-it-works.md).

Every recorded entry is checked against the source. A service needs existing
directories. An endpoint needs a file under one of its service's directories,
the line of the route declaration and that declaration copied verbatim as
`evidence`. The verb and the end of the path must agree with the evidence.
Accepted entries are kept and rejected ones go back to the model with the
reason, so a large system does not have to fit into one reply.

The model sees only the files git tracks, minus vendored dependencies
(`node_modules`, `vendor`). Several checkouts of one system can be mounted
side by side. `_run` records the commit of each checkout and whether it had
local changes.

Guards: older tool results are dropped when the context fills up (in one batch,
so a prompt cache keeps working), API errors are retried, and repeating the
same call three times triggers a warning and then a forced submit. A run always
writes an output, and `_run` records whether it was accepted.

## Run

```bash
python agent_extract.py --repo <checkout> [<checkout> ...] --system-name <system> --effort none
python test_record.py && python test_parse_call.py
python test_loop_guard.py <checkout of spring-cloud-movie-recommendation>
```

Default model: `spark-x2.5-4b` in LM Studio, temperature 0, 60 steps. Use
`--native-tools` for models that call tools through the OpenAI tools API, and
`--ctx-chars` for a server with a small context. Score with
`../experiment_01/evaluate.py` or open `../experiment_01/out/viewer.html`.

## Results (movie, inbound, M2)

| workflow | model | F1 | false positives | wall |
|---|---|---:|---:|---:|
| per-file | spark-x2.5-4b | 0.718 | 11 | 247 s |
| agent, effort none | spark-x2.5-4b | 1.000 | 0 | 122 s |
| agent, effort low | spark-x2.5-4b | 1.000 | 0 | 348 s |

Same model: exploring the repository removes the Feign client methods that the
per-file workflow reports as inbound endpoints.

## Results: DeepSeek-V4.1-Flash-1017 on all three systems (inbound, M2)

Wafer, `--native-tools --effort none --max-tokens 24000`, 60 steps.

| system | found / ground truth | false positives | F1 | CIMET F1 | steps | list price | wall |
|---|---:|---:|---:|---:|---:|---:|---:|
| movie-recommendation | 14 / 14 | 0 | 1.000 | 1.000 | 9 | $0.003 | 19 s |
| xs2a | 42 / 50 | 0 | 0.913 | 0 found | 59 | $0.057 | 1051 s |
| geoserver-cloud | 6 / 7 | 0 | 0.923 | 0.400 | 56 | $0.017 | 1082 s |

On xs2a and geoserver-cloud about 900 s of the wall time is one API request
that timed out and was retried. On xs2a the agent found the routes declared on
the interfaces in `xs2a-server-api`, which CIMET misses. The 8 endpoints it
missed are payment and authorisation variants. It used 59 of its 60 steps, so
more steps may close that gap. On geoserver-cloud it missed
`GET /accessDenied.html`.
