# Render configuration and release procedure

Set these variables on the Render backend service. Values for credentials must be generated or copied into Render's secret store; never commit them.

## Required environment variables

| Variable | Render value or requirement |
| --- | --- |
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `JWT_SECRET` | Unique random secret, at least 32 characters |
| `DATABASE_URL` | Render PostgreSQL URL using `postgresql+asyncpg://` |
| `REDIS_URL` | Reachable Redis URL |
| `QDRANT_URL` | Reachable Qdrant HTTPS endpoint |
| `GITHUB_CLIENT_ID` | GitHub OAuth application client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth application secret |
| `GITHUB_REDIRECT_URI` | `https://codepilot-j8ex.onrender.com/api/v1/auth/callback` (must match GitHub OAuth app settings) |
| `LLM_PROVIDER` | Provider name: `openai`, `anthropic`, `gemini`, `deepseek`, or `ollama` |
| `LLM_MODEL` | Model identifier supported by the selected provider |
| `EMBEDDING_PROVIDER` | `openai`, `bge`, `nomic`, or `voyage` |
| `EMBEDDING_MODEL` | Model identifier supported by the selected embedding provider |
| `VECTOR_DIMENSION` | Must match the selected embedding model and the existing Qdrant collection |
| `CORS_ORIGINS` | JSON/list of trusted frontend origins |

Provider credentials are conditional: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or `DEEPSEEK_API_KEY` for the matching `LLM_PROVIDER`; `OPENAI_API_KEY` or `VOYAGE_API_KEY` for the matching embedding provider. For an API deployment without paid OpenAI calls, use `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3.3` (or a model available on your service), `OLLAMA_BASE_URL=https://<reachable-ollama-service>`, `EMBEDDING_PROVIDER=bge`, `EMBEDDING_MODEL=BAAI/bge-m3`, and `VECTOR_DIMENSION=1024`. The Ollama URL must be reachable from Render. BGE downloads its model at runtime and is not verified for Render's memory, disk, or network limits. Provision a Qdrant collection with the same 1024 dimension before indexing; an existing collection with another dimension will fail explicitly. No live provider configuration was tested in this audit.

Useful optional variables include `HEALTH_CHECK_TIMEOUT_SECONDS` (default `2`), `QDRANT_API_KEY`, `CACHE_TTL_SECONDS`, `DATABASE_ECHO` (keep false), `LOG_LEVEL`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `OTEL_EXPORTER_ENDPOINT`, and `OTEL_SERVICE_NAME`. Render supplies `PORT`; the Docker command uses it.

## Schema migration

Schema creation no longer runs during web-process startup. The backend includes an Alembic baseline, and future schema changes must be committed as explicit revisions. Run a single migration command in a controlled release step, not in every web worker:

```sh
cd backend
alembic upgrade head
```

For a fresh database, this creates the current model tables. The baseline uses SQLAlchemy metadata with `checkfirst=True`, so it creates missing tables/indexes and does not drop data; it is not a substitute for migrations that alter existing columns or constraints. Before using it against an existing database, take a backup and compare the live schema to current models. If the live schema already matches the baseline, record the baseline without executing it:

```sh
cd backend
alembic stamp 0001_baseline
alembic upgrade head
```

Do not stamp an unverified schema. Do not run `alembic upgrade` concurrently from multiple workers. The existing Render database was not modified or inspected with credentials, so schema parity and migration safety remain unverified.

## Review execution limitation

Reviews currently run through FastAPI `BackgroundTasks`. Their state and output are stored in PostgreSQL, but queued work itself is not durable: a Render restart can terminate a review and leave its row `pending` or `running`. On startup, rows still `pending` after 30 minutes are marked failed with a retry message; `running` rows are deliberately not timed out because there is no heartbeat to separate a live long review from an interrupted one. Failed task exceptions are logged with a request/review identifier and update the row to `failed` when the database remains available. Deployments should drain traffic and avoid restarting during active reviews. A durable queue is required before promising restart-safe execution; the current stack does not yet define an atomic queue/worker protocol or retry policy.

## Safe verification after an authorized deploy

Check `GET /health` for process liveness and `GET /ready` for bounded PostgreSQL, Redis, and Qdrant reachability. Then use a dedicated test account and repository to verify OAuth, owned-repository access, one persisted review ID, terminal state, report/log uniqueness, and provider results. Avoid repeated or load-generating reviews. No deployment, secret changes, or production database commands were performed in this audit.
