# How the agent works

`agent_extract.py` gives the model a task, a set of tools and up to 60 steps.
In each step the model calls one or more tools and gets their results back.
It builds the result piece by piece with `record`. Every piece is checked against
the source code. The run ends when the model calls `submit` and nothing is rejected.

## The loop and its tools

```mermaid
flowchart LR
    subgraph loop["Agent loop: one step"]
        direction TB
        start(["system prompt: task, rules, JSON schema<br/>user: extract the services and endpoints"]) --> step{"step ≤ 60?"}
        step -- yes --> llm["LLM call, temperature 0<br/>(oldest tool results stubbed<br/>if the prompt gets too long)"]
        llm --> parse{"tool call<br/>in the reply?"}
        parse -- yes --> guard{"same call for<br/>the 3rd time?"}
        guard -- no --> exec[["execute the tool →"]]
        exec --> res["append to the messages"]
        guard -- "yes: LOOP warning<br/>instead of a result" --> res
        parse -- "no: error<br/>call a tool" --> res
        res --> done{"submit<br/>accepted?"}
        done -- "no: next step" --> step
        done -- yes --> out(["write agent_ir.*.json<br/>.messages.json, .log"])
        step -- no --> out
    end
    subgraph tools["Tools the model can call"]
        direction TB
        subgraph explore["1. explore: read-only, git-tracked files"]
            direction TB
            t1["list_dir(path)"] ~~~ t2["find(pattern, path)<br/>file-name glob, ≤ 100 paths"]
            t2 ~~~ t3["grep(pattern, path)<br/>Python regex, ≤ 60 hits"]
            t3 ~~~ t4["read_file(path, start)<br/>300 numbered lines"]
        end
        subgraph build["2. build the result"]
            direction TB
            t5["record(json)<br/>services, endpoints"] --> v{"validator:<br/>backed by<br/>the source?"}
            t6["submit(json?)<br/>last part, then finish"] --> v
            v -- yes --> kept[("recorded result")]
            v -- no --> back["reason goes back<br/>to the model"]
        end
        explore ~~~ build
    end
    loop ~~~ tools
```

- **Exploration tools** see only files tracked by git, minus `node_modules` and
  `vendor`. Several checkouts can be mounted side by side as one system.
- **`record`** takes `{"services": [...], "files": [...]}`. Accepted entries
  stay in the result. A rejected entry comes back with the reason, the model
  fixes it and records it again. So a system with 50 endpoints never has to fit
  into one reply.
- **The validator** accepts an endpoint only when:
  - its file exists and lies under a directory of a recorded service,
  - `className` and `methodName` appear in that file,
  - `evidence` is found within 3 lines of `line`,
  - the HTTP verb agrees with the evidence,
  - the path ends with the route literal in the evidence.
- **`submit`** is accepted only if nothing in its last part was rejected and at
  least one service is recorded.
- **Tool call format:** with `--native-tools` the tools are sent as an OpenAI
  `tools` array, and the model may make several calls in one reply. Without it,
  the tool list is in the system prompt, and the model writes one
  `<tool_call>name<arg_key>k</arg_key><arg_value>v</arg_value></tool_call>`
  per reply.
- **Guards:** 4 steps before the limit the model is told to record what it has
  and submit. The 4th loop warning, or ignoring the order to submit, stops the
  run. An API error that persists after the retries also ends the run. Every run
  writes its output, and `_run.accepted` says whether `submit` succeeded.

## Example run

bonsai2-27b with `--native-tools --effort none` on
spring-cloud-movie-recommendation (commit `5aa5ee9e`, 93 files, 6 services).
Numbers in brackets are steps. Steps 2–6 make several calls in one reply.

```mermaid
sequenceDiagram
    participant M as Model (bonsai2-27b)
    participant H as agent_extract.py
    Note over M,H: explore
    M->>H: [1] list_dir /
    H-->>M: config-service/ eureka-service/ movie-service/<br/>recommendation-client/ recommendation-service/ user-service/ dump/
    M->>H: [2] list_dir, 6 calls, one per service
    M->>H: [3] find src/main/java/**/*.java, 6 calls
    H-->>M: the Java files of each service
    M->>H: [4-6] read_file, 15 calls: main classes, controllers, Feign clients
    Note over M,H: record as it goes
    M->>H: [7] record 6 services
    H-->>M: Recorded 6 new. Services with no endpoints recorded yet: all 6
    M->>H: [8] record MovieController, 4 endpoints
    H-->>M: Recorded 4 new: GET /movie, GET /movie/list, GET /movie/{movieId}, GET /movie/dummyData
    M->>H: [9] record MainController of recommendation-client, 2 endpoints
    Note over M,H: the Feign clients read in step 6 are outbound calls, so they are not recorded
    M->>H: [10] record RecommendationController, 6 endpoints
    M->>H: [11] record UserController, 2 endpoints
    H-->>M: GET /user accepted. GET /user/{userId} REJECTED: path does not end with the route in the evidence
    Note over M,H: stuck on one entry
    M->>H: [12-13] the same entry again
    H-->>M: REJECTED, same reason
    M->>H: [14] the same call for the 3rd time
    H-->>M: LOOP warning 1/3, not executed. Directories you have not opened yet: /dump
    M->>H: [15-17] list_dir /dump, read_file of 2 metadata files
    M->>H: [18-19] the same record again
    H-->>M: LOOP warning 2/3, then 3/3: record what you have and submit NOW
    M->>H: [20] submit
    H-->>M: ACCEPTED: 6 services, 13 endpoints
```

What one `record` call looks like (step 8, first of its 4 endpoints):

```json
{"files": [{"path": "/movie-service/src/main/java/com/example/MovieController.java",
  "service": "movie-service",
  "endpoints": [{"className": "MovieController", "methodName": "getAllMovies",
    "httpMethod": "GET", "path": "/movie", "line": 31,
    "evidence": "@RequestMapping(method = RequestMethod.GET)",
    "framework": "Spring", "confidence": "high"}]}]}
```

The class carries `@RequestMapping("/movie")`, so the model joined that prefix
into `path`.

The rejection in step 11: the model copied the declaration as
`@RequestMapping(value="/ {userId}", ...)`, with a space that is not in the
source. The validator then compared the route with the spaces, so it rejected
the entry. Each retry sent the same text. The validator now ignores whitespace,
and the same entry passes.

**Result:** scored against the ground truth: 13 of 14 endpoints, 0 false
positives, F1 0.963. The only miss is the rejected `GET /user/{userId}`.
The run took 20 steps and 428 s. It used 177 k input tokens (168 k of them
from the prompt cache) and 3 k output tokens. The full log is in
`out/agent_ir.spring-cloud-movie-recommendation.bonsai2-27b.none.log`.
