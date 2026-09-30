# Ground truth: labeling protocol

Inbound HTTP endpoints and outbound REST calls, labelled by reading the source,
not by running an extractor. Without it the experiment could only measure
agreement between CIMET and an LLM.

| system | commit | frame | labelled |
|---|---|---|---|
| spring-cloud-movie-recommendation | `5aa5ee9e` | whole system (31 files) | 14 endpoints, 9 outbound calls |
| geoserver-cloud | `70cf0825` | whole system (718 files) | 7 endpoints |
| xs2a | `2603384e` | `xs2a-server-api/src/main/java/**` (264 files) | 50 endpoints |

Labelled by Jaroslav Knápek, 2026-09-09. Candidates were found by an annotation
sweep, and every candidate file was then read in full.

```bash
python groundtruth/validate.py --all    # checkouts in $CLONE_DIR, large CIMET IRs in $CIMET_DIR
```

`validate.py` checks internal consistency and re-opens every entry at its file
and line to confirm the verb, path and handler are really there.

## Rules

- **Inbound endpoint:** a (route, HTTP method) pair declared in this
  repository's source on a request-handling type. One method with two paths is
  two endpoints.
- **Outbound call:** a route used by a client (`@FeignClient`,
  `RestTemplate`, `WebClient`). Never counted as an endpoint.
- **Excluded**, with the reason in `excluded`: routes that exist only at
  runtime (Spring Data REST, Actuator, Eureka), routes defined in external
  configuration, and constructs that only look like endpoints.
- **Scope is declared routes, not the runtime HTTP surface.** Both extractors
  read source only.

## Normalization (M2)

In this order: resolve `${prop:default}` to its default, replace `{...}` with
`{}`, drop the query string, host and `:param` segments, collapse slashes, drop
the trailing slash, lowercase. Braces must go before the `?` split, otherwise
CIMET's `{?}` is cut in half.

## Matching levels

| level | key | a miss here means |
|---|---|---|
| M1 | service + verb + declared path | different notation (not an accuracy measure) |
| M2 | service + verb + normalized path | a real disagreement about the route |
| M3 | service + normalized path | route found, verb wrong |
| M4 | service + class + method | code found even if the path is wrong |

M4 ignores a leading underscore (xs2a annotates `_getAccountList`, the
controller overrides `getAccountList`).

## Frames

A large system is labelled inside a **frame**: a module, labelled
exhaustively, so recall stays computable. Predictions outside the frame are
not scored. On xs2a, CIMET's 12 endpoints all lie outside the frame, so inside
it CIMET finds 0 of 50 and its precision is undefined, not zero.

## Limitations

Single labeller (no inter-rater agreement), small systems, Java/Spring only.
