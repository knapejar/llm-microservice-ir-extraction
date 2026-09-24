# Results

System: `mdeket/spring-cloud-movie-recommendation` @ `5aa5ee9e`, 6 services,
31 main-source `.java` files. Baseline: CIMET 1.2.1, **14 inbound endpoints**
and **9 outbound `RestCall`s**. Prompt: `prompt_appendix_a.txt` (Appendix A).
One request per file, temperature 0, one run per model.

| model | schema ok | endpoints | ratio | route F1 | code F1 | halluc. | role-sep. err | in/out tok | list $ | wall |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| gemini-2.5-flash-lite | 31/31 | 23 | 1.64 | 0.78 | 0.76 | 0.0% | 39.1% | 17 608 / 3 978 | 0.0034 | 32.1 s |
| gemini-3.5-flash-lite | 31/31 | 14 | 1.00 | **1.00** | **1.00** | 0.0% | 0.0% | 17 608 / 3 174 | 0.0030 | 34.3 s |

## Role separation

Both models found the same 14 inbound endpoints (recall 1.00), with paths,
HTTP methods and method names matching CIMET.

`gemini-2.5-flash-lite` additionally reported the 9 `@FeignClient` interface
methods as inbound endpoints. They match CIMET's 9 outbound `RestCall`s 1:1:
the calls were detected correctly but classified as inbound.
`gemini-3.5-flash-lite` returned only the 14 inbound endpoints.

A Feign interface method is syntactically identical to a controller method
(`@RequestMapping(method = ..., value = ...)`); the only distinguishing evidence
is `@FeignClient` on the interface.

## Hallucination rate is 0%

Every surplus endpoint has a counterpart in CIMET's outbound set. The observed
failure is **misclassification, not fabrication**, so the two are reported as
separate metrics.

## Confidence

Both models labelled **100% of endpoints `confidence: high`**, including the 9
misclassified ones. The field does not discriminate correct from incorrect
results.

## Limitations

- One system, one run per model.
- Small, conventional Spring system; generated interfaces, other frameworks and
  larger systems are not covered.
- Per-file prompting gives the model no cross-file context.
