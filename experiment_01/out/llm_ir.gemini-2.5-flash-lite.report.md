# CIMET vs. LLM — endpoint extraction agreement

- model: `gemini-2.5-flash-lite`, temperature 0, prompt: `prompt_appendix_a.txt`
- system: `clone/spring-cloud-movie-recommendation`
- files sent: 31, schema-valid responses: 31/31
- tokens: 17608 in / 3978 out — list price $0.0034, wall 32.1 s
- CIMET endpoints: **14**, LLM endpoints: **23**, ratio 1.64

## route-level  (service + verb + canonical path)

| tp | fp | fn | precision | recall | F1 | Jaccard |
|---:|---:|---:|---:|---:|---:|---:|
| 14 | 8 | 0 | 0.6364 | 1.0 | 0.7778 | 0.6364 |

**LLM only (8):**

- `recommendation-client GET /movie`
- `recommendation-client GET /movie/dummydata`
- `recommendation-client GET /movie/list`
- `recommendation-client GET /newuser`
- `recommendation-client GET /recommendation/dummydata`
- `recommendation-client GET /recommendation/recommend/user/{}`
- `recommendation-client GET /user`
- `recommendation-client GET /user/{}`

## code-level   (service + class + method)

| tp | fp | fn | precision | recall | F1 | Jaccard |
|---:|---:|---:|---:|---:|---:|---:|
| 14 | 9 | 0 | 0.6087 | 1.0 | 0.7568 | 0.6087 |

**LLM only (9):**

- `recommendation-client MovieService getMovies`
- `recommendation-client MovieService insertDummyData`
- `recommendation-client RecommendationClientService getMovies`
- `recommendation-client RecommendationClientService getRecommendationData`
- `recommendation-client RecommendationClientService getUserDetails`
- `recommendation-client RecommendationService insertDummyData`
- `recommendation-client UserService createUser`
- `recommendation-client UserService getUser`
- `recommendation-client UserService getUsers`

## Where the LLM's surplus endpoints belong

CIMET outbound calls (`RestCall`): 9

| category | count |
|---|---:|
| surplus endpoints over CIMET | 9 |
| of which match a CIMET `RestCall` (= outbound, misclassified) | 9 |
| of which unexplained (hallucination candidates) | 0 |
| **hallucination rate** | **0.0%** |
| **role-separation error rate** | **39.1%** |

## Other metrics

| metric | CIMET | LLM |
|---|---:|---:|
| duplicate endpoints (route key) | 0 (0.0%) | 1 (4.3%) |
| schema validity | n/a (deterministic) | 31/31 = 100.0% |
| confidence high/medium/low | n/a | 23/0/0 |
| framework labels | n/a | {'Spring': 23} |

## Per service

| service | CIMET | LLM | match (route) |
|---|---:|---:|---:|
| movie-service | 4 | 4 | 4 |
| recommendation-client | 2 | 10 | 2 |
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
| recommendation-client | GET | `/movie` | MovieService.getMovies | high |
| recommendation-client | GET | `/movie/dummyData` | MovieService.insertDummyData | high |
| recommendation-client | GET | `/movie/list?ids={ids}` | RecommendationClientService.getMovies | high |
| recommendation-client | GET | `/newuser` | UserService.createUser | high |
| recommendation-client | GET | `/recommendation/dummyData` | RecommendationService.insertDummyData | high |
| recommendation-client | GET | `/recommendation/recommend/user/{userId}` | RecommendationClientService.getRecommendationData | high |
| recommendation-client | GET | `/user` | UserService.getUsers | high |
| recommendation-client | GET | `/user/{userId}` | RecommendationClientService.getUserDetails | high |
| recommendation-client | GET | `/user/{userId}` | UserService.getUser | high |
| recommendation-service | GET | `/recommendation/dummyData` | RecommendationController.addDummyData | high |
| recommendation-service | GET | `/recommendation/movie` | RecommendationController.getAllMovies | high |
| recommendation-service | GET | `/recommendation/movie/{movieId}` | RecommendationController.getMovie | high |
| recommendation-service | GET | `/recommendation/recommend/user/{userId}` | RecommendationController.getRecommendationForUser | high |
| recommendation-service | GET | `/recommendation/user` | RecommendationController.getAllUsers | high |
| recommendation-service | GET | `/recommendation/user/{userId}` | RecommendationController.getUser | high |
| user-service | GET | `/user` | UserController.getAllUsers | high |
| user-service | GET | `/user/{userId}` | UserController.getUsers | high |
