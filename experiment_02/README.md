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
so a prompt cache keeps working), and API errors are retried. Repeating the same
call three times triggers a warning; a call whose earlier result was dropped does
not count. After three warnings only `record` and `submit` run, and the run
stops after five more refused calls. After 15 steps without a new endpoint the
model is told to record what it has found. A run always writes an output, and
`_run` records whether it was accepted.

## Run

```bash
python agent_extract.py --repo <checkout> [<checkout> ...] --system-name <system> --effort none
python test_record.py && python test_parse_call.py
python test_loop_guard.py <checkout of spring-cloud-movie-recommendation>
CLONE=<dir with the checkouts> LLM_API_KEY=<key> sh run_pool.sh <model> [effort]
python merge_runs.py
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

## Benchmark pool: DeepSeek-V4.1-Flash-1017, effort low (inbound)

`run_pool.sh` runs the agent on 35 open-source systems, three runs at a time,
with `--native-tools --effort low --max-tokens 24000`. Large systems are split
into units (a service, a repository or a module): a single run declares itself
done long before it has seen a few hundred endpoints. Only three systems have a
ground truth; the others were checked against a grep of route declarations
(outbound Retrofit and Feign clients and tests excluded) and the differences
read by hand.

| system | units | endpoints | list price | check |
|---|---:|---:|---:|---|
| spring-cloud-movie-recommendation | 1 | 14 | $0.003 | ground truth F1 1.000 |
| xs2a | 1 | 159 | $0.082 | ground truth F1 0.980 (labelled module) |
| geoserver-cloud | 1 | 18 | $0.057 | ground truth F1 0.320: prefixed routes with each app's `${geoserver.base-path}` |
| six small repositories | 6 | 38 | $0.012 | complete |
| pitstop | 1 | 32 | $0.005 | complete, including MVC actions |
| robot-shop | 1 | 46 | $0.008 | complete, plus nginx proxy routes |
| sock-shop | 1 (8 repos) | 65 | $0.011 | complete |
| eShop | 1 | 82 | $0.094 | gateway routes and gRPC methods also counted |
| ccpay-payment-app | 1 | 74 | $0.013 | 74 / 74 |
| pravega | 1 | 27 | $0.021 | complete, generated health API skipped |
| train-ticket | 1 | 272 | $0.067 | 272 / 272 |
| apollo | 1 | 204 | $0.081 | about 91 % |
| kapua | 1 | 281 | $0.131 | 235 code locations, about 79 %; routes recorded with and without `/v1` |
| openlmis | 10 | 382 | $0.124 | complete; one run on all ten repositories found 218 |
| inlong | 2 | 305 | $0.108 | the `openapi` controllers (49 routes) missed |
| camunda | 3 | 430 | $0.283 | optimize 145 / 145, gateway-rest 213 / 247 |
| spinnaker | 10 | 727 | $0.338 | complete except gate (about 87 %) |
| **total** | 43 | | **$1.44** | |

The six small repositories are golang-crud-rest-api-gin, crud-tutorial-csharp,
node-js-restful-api-example, E-commerce-Microservice, rasa-sdk and
microservices-demo. No recorded endpoint was invented: the evidence check
rejects any route not declared at the cited line. In Spinnaker the agent left
out the ~710 route declarations of Retrofit clients, which are outbound calls.

GLM-5.3-Flash with reasoning (`--effort default`) on the 14 smaller systems
costs $0.38, about twice as much. It scores the same on movie-recommendation
and xs2a and 0.636 on geoserver-cloud, but finds fewer endpoints in large
repositories (85 against 159 in the whole of xs2a). `merge_runs.py` merges the
runs of all models into a draft baseline per system (`out/pool/baseline/`),
where each endpoint lists the models that found it.
