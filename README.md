# LLM microservice IR extraction

Can an LLM extract the inbound HTTP endpoints of a microservice system from its
source code, and how does it compare with the deterministic extractor CIMET?
Every run is scored against a manually labelled ground truth on three Java
systems: spring-cloud-movie-recommendation, xs2a and geoserver-cloud.

| | what it does |
|---|---|
| [`experiment_01`](experiment_01/) | **Per-file:** the LLM reads one source file at a time. Also holds the ground truth, the evaluation and the results viewer (`out/viewer.html`). |
| [`experiment_02`](experiment_02/) | **Agent:** the LLM explores the whole repository with read-only tools and submits one result. |

Main finding so far: the same small model (spark-x2.5-4b) reaches F1 0.718 per
file and 1.000 as an agent on movie-recommendation. Working per file, it
reports Feign client methods (outbound calls) as endpoints.
