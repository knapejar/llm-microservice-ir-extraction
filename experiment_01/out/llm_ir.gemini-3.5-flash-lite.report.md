# CIMET vs. LLM — endpoint extraction agreement

- model: `gemini-3.5-flash-lite`, temperature 0, prompt: `prompt_appendix_a.txt`
- system: `clone/spring-cloud-movie-recommendation`
- files sent: 31, schema-valid responses: 31/31
- tokens: 17608 in / 3174 out — list price $0.003, wall 34.3 s
- CIMET endpoints: **14**, LLM endpoints: **14**, ratio 1.00

## route-level  (service + verb + canonical path)

| tp | fp | fn | precision | recall | F1 | Jaccard |
|---:|---:|---:|---:|---:|---:|---:|
| 14 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 |

## code-level   (service + class + method)

| tp | fp | fn | precision | recall | F1 | Jaccard |
|---:|---:|---:|---:|---:|---:|---:|
| 14 | 0 | 0 | 1.0 | 1.0 | 1.0 | 1.0 |

## Where the LLM's surplus endpoints belong

CIMET outbound calls (`RestCall`): 9

| category | count |
|---|---:|
| surplus endpoints over CIMET | 0 |
| of which match a CIMET `RestCall` (= outbound, misclassified) | 0 |
| of which unexplained (hallucination candidates) | 0 |
| **hallucination rate** | **0.0%** |
| **role-separation error rate** | **0.0%** |

## Other metrics

| metric | CIMET | LLM |
|---|---:|---:|
| duplicate endpoints (route key) | 0 (0.0%) | 0 (0.0%) |
| schema validity | n/a (deterministic) | 31/31 = 100.0% |
| confidence high/medium/low | n/a | 14/0/0 |
| framework labels | n/a | {'Spring': 14} |

## Per service

| service | CIMET | LLM | match (route) |
|---|---:|---:|---:|
| movie-service | 4 | 4 | 4 |
| recommendation-client | 2 | 2 | 2 |
| recommendation-service | 6 | 6 | 6 |
| user-service | 2 | 2 | 2 |

## All LLM endpoints

| service | verb | path (raw) | class.method | conf |
|---|---|---|---|---|
| movie-service | GET | `/movie` | MovieController.getAllMovies | high |
| movie-service | GET | `/movie/dummyData` | MovieController.insertDummyData | high |
| movie-service | GET | `/movie/list` | MovieController.getListMovies | high |
| movie-service | GET | `/movie/{movieId}` | MovieController.getMovie | high |
| recommendation-client | GET | `/api/recommendation/user/{userId}` | MainController.getRecommendation | high |
| recommendation-client | GET | `/api/userDetails/{userId}` | MainController.getUserDetails | high |
| recommendation-service | GET | `/recommendation/dummyData` | RecommendationController.addDummyData | high |
| recommendation-service | GET | `/recommendation/movie` | RecommendationController.getAllMovies | high |
| recommendation-service | GET | `/recommendation/movie/{movieId}` | RecommendationController.getMovie | high |
| recommendation-service | GET | `/recommendation/recommend/user/{userId}` | RecommendationController.getRecommendationForUser | high |
| recommendation-service | GET | `/recommendation/user` | RecommendationController.getAllUsers | high |
| recommendation-service | GET | `/recommendation/user/{userId}` | RecommendationController.getUser | high |
| user-service | GET | `/user` | UserController.getAllUsers | high |
| user-service | GET | `/user/{userId}` | UserController.getUsers | high |
