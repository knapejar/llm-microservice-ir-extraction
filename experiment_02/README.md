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
reason, so a large system does not have to fit into one reply. One verb and
route in one file is one endpoint, and the same declaration recorded again
with a prefix added or dropped replaces the earlier path.

The model sees only the files git tracks, minus vendored dependencies
(`node_modules`, `vendor`). Several checkouts of one system can be mounted
side by side. `_run` records the commit of each checkout and whether it had
local changes.

Guards: when the context fills up, older tool results and the arguments of
long earlier calls are dropped, and if that is not enough the oldest steps go
whole, replaced by a note listing the files with recorded endpoints. This
happens in one batch, so a prompt cache keeps working. API errors are retried. Repeating the same
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
python agent_cli.py <state.json> init --repo <checkout> --system-name <system> --model <name>
python spinnaker_compare.py --cimet <CIMET IR of spinnaker>
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

| system | units | endpoints (verb + route) | list price | check |
|---|---:|---:|---:|---|
| spring-cloud-movie-recommendation | 1 | 14 | $0.003 | ground truth F1 1.000 |
| xs2a | 1 | 157 | $0.082 | ground truth F1 0.980 (labelled module) |
| geoserver-cloud | 1 | 18 | $0.057 | ground truth F1 0.320: prefixed routes with each app's `${geoserver.base-path}` |
| six small repositories | 6 | 38 | $0.013 | complete |
| pitstop | 1 | 32 | $0.005 | complete, including MVC actions |
| robot-shop | 1 | 46 | $0.008 | complete, plus nginx proxy routes |
| sock-shop | 1 (8 repos) | 65 | $0.011 | complete |
| eShop | 1 | 81 | $0.094 | gateway routes and gRPC methods also counted |
| ccpay-payment-app | 1 | 74 | $0.013 | 74 / 74 |
| pravega | 1 | 27 | $0.021 | complete, generated health API skipped |
| train-ticket | 1 | 272 | $0.067 | 272 / 272 |
| apollo | 1 | 204 | $0.081 | about 91 % |
| kapua | 1 | 297 | $0.165 | 297 / 297 |
| openlmis | 10 | 369 | $0.272 | complete; one run on all ten repositories found 218 |
| inlong | 2 | 357 | $0.183 | manager 322 / 322; tubemq names some pages two ways |
| camunda | 3 | 475 | $0.296 | optimize 145 / 145, gateway-rest 259 (complete) |
| spinnaker | 10 | 756 | $0.577 | 1 route missed, see below |
| **total** | 43 | 3282 | **$1.95** | |

Until the fix of context trimming, record calls of a few hundred endpoints and
then hundreds of short calls filled the context, so every new tool result was
dropped as it arrived and the agent re-read the same file until it gave up.
camunda gateway-rest, openlmis-referencedata and all of Spinnaker ran with the
fixed agent (tag `agent-2026-10-26`); kapua and inlong with a partial fix; the
rest still with the bug, which matters for apollo, train-ticket and
camunda-other.

**Spinnaker with the fixed agent.** A grep of route declarations finds 759
lines in the ten services; the agent records 756 endpoints. Read by hand, the
difference is one missed route (`POST /pipelines/{id}/evaluateExpression` in
gate) and five declarations that repeat an already recorded verb and route with
other `consumes` or `params`. The agent also resolves a route inherited from
`AbstractCommitController` in igor into its four concrete controllers and finds
a `@WebServlet` in keel, which the grep misses. It records none of the 464
route declarations in Retrofit and Feign clients. The only debatable entry is
`POST /graphql` in keel, served by the DGS framework. Before the fix the same
services gave 720 endpoints (gate 248 instead of 283). clouddriver used all 300
steps re-checking files it had recorded and cost $0.29 of the $0.58.
These numbers come from the grep comparison and a hand check of the
differences only; a full manual review of the Spinnaker endpoints is in progress.

**Spinnaker side by side.** `spinnaker_compare.py` puts the endpoints of each
model and of CIMET into one table per service, with the verdicts of a hand check
of the disagreements (`spinnaker_review.json`):
https://knapejar.github.io/llm-microservice-ir-extraction/spinnaker/.
`agent_cli.py` exposes the agent's tools as a command line, so a model working
in an interactive session runs the same task with the same validation.
The endpoints every finished run found, plus the confirmed disagreements, form a
draft ground truth of 752 endpoints (`../experiment_01/groundtruth/spinnaker.gt.json`),
which the viewer scores like the other systems:
https://knapejar.github.io/llm-microservice-ir-extraction/viewer/#spinnaker.

| source | found | tp | fp | fn | F1 (M2) |
|---|---:|---:|---:|---:|---:|
| Opus 5.5, medium effort, via `agent_cli.py` | 753 | 751 | 2 | 1 | 0.998 |
| DeepSeek-V4.1-Flash, effort low | 756 | 750 | 6 | 2 | 0.995 |
| GLM-5.3-Flash, effort default | 442 | 428 | 14 | 324 | 0.717 |
| CIMET main | 54 | 51 | 3 | 701 | 0.127 |

The draft is built from the runs it scores, so the agreeing models score high by
construction; only the hand-checked disagreements discriminate. There, most
differences are the verb of a mapping without a method (ANY), a class prefix
invented (GLM, keel `VetoController`) or doubled (DeepSeek, two ECS controllers),
and two routes of `clouddriver-alicloud`, which is left out of the build. GLM
stopped early on gate (loop guard) and clouddriver. CIMET main finds only kayenta
and echo-web and reads a statically imported `method = POST` as ALL.

The six small repositories are golang-crud-rest-api-gin, crud-tutorial-csharp,
node-js-restful-api-example, E-commerce-Microservice, rasa-sdk and
microservices-demo. No recorded endpoint was invented: the evidence check
rejects any route not declared at the cited line.

GLM-5.3-Flash with reasoning (`--effort default`) on the 14 smaller systems
costs $0.38, about twice as much. It scores the same on movie-recommendation
and xs2a and 0.636 on geoserver-cloud, but finds fewer endpoints in large
repositories (85 against 159 in the whole of xs2a). `merge_runs.py` merges the
runs of all models into a draft baseline per system (`out/pool/baseline/`),
where each endpoint lists the models that found it.
