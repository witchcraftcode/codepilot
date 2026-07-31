# CodePilot AI

**Multi-Agent Code Review & Repository Intelligence Platform**

A production-grade multi-agent AI system that performs intelligent code reviews on GitHub repositories. Specialized agents collaborate to analyze architecture, security, performance, testing, documentation, and coding practices using RAG, tool calling, and repository-aware reasoning.

Built as a startup-quality AI product — not a tutorial project.

---

## Architecture

```
User → GitHub URL → Clone & Parse → AST Chunking → Embeddings → Qdrant
                                                                    ↓
                                                              LangGraph Workflow
                    ┌─────────────────────────────────────────────────┐
                    │ Planner → Repository → Architecture → Security  │
                    │ → Performance → Testing → Documentation → Style │
                    │ → Dependencies → Summary → Final Report         │
                    └─────────────────────────────────────────────────┘
                                                                    ↓
                                                              Next.js UI
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python, Asyncio |
| AI Orchestration | **LangGraph** (primary), LangChain (utilities) |
| LLM | Configurable: OpenAI, Anthropic, Gemini, DeepSeek, Ollama |
| Vector DB | Qdrant |
| Embeddings | OpenAI, BGE-M3, Nomic, Voyage |
| Database | PostgreSQL |
| Cache | Redis |
| Frontend | Next.js, Tailwind CSS, Shadcn UI |
| Deployment | Docker Compose, Nginx |
| Auth | GitHub OAuth + JWT |
| Observability | LangSmith, OpenTelemetry |
| Evaluation | RAGAS |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- OpenAI API key (or other LLM provider)
- GitHub OAuth app (optional, for auth)

### 1. Clone & Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start Services

```bash
docker compose up -d
```

Services:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Qdrant**: http://localhost:6333

### 3. Local Development (without Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/repository` | Index a GitHub repository |
| POST | `/api/v1/review` | Run multi-agent code review |
| POST | `/api/v1/chat` | Chat with repository (RAG) |
| POST | `/api/v1/security` | Security audit |
| POST | `/api/v1/tests` | Generate unit tests |
| POST | `/api/v1/documentation` | Auto-generate docs |
| POST | `/api/v1/explain` | Explain a function |
| POST | `/api/v1/pr-review` | Review a pull request diff |
| GET | `/api/v1/history` | Review history |
| GET | `/api/v1/scores/{id}` | Repository health scores |
| POST | `/api/v1/feedback` | Submit review feedback |

## Multi-Agent System

| Agent | Responsibility |
|-------|---------------|
| **Planner** | Decides which agents to run based on request |
| **Repository** | Structure, languages, frameworks, dependencies |
| **Architecture** | SOLID, layering, modularity, separation of concerns |
| **Security** | OWASP, secrets, injection, auth vulnerabilities |
| **Performance** | N+1 queries, blocking ops, inefficient algorithms |
| **Testing** | Coverage gaps, test generation suggestions |
| **Documentation** | README, API docs, docstrings |
| **Style** | PEP8/ESLint, naming, code smells |
| **Dependencies** | CVEs, outdated packages, unused deps |
| **Summary** | Overall score, top issues, remediation roadmap |

The Planner skips irrelevant agents — a security-focused request only runs Security + Dependencies + Summary.

## RAG Pipeline

Hierarchical chunking (not character-based):

```
Repository → Folder → File → Class → Function → Method
```

Supported languages: **Python, JavaScript/TypeScript, Java, C++, Go, Rust**

## Configuration

All providers are configurable via environment variables:

```bash
LLM_PROVIDER=openai          # openai | anthropic | gemini | deepseek | ollama
EMBEDDING_PROVIDER=openai    # openai | bge | nomic | voyage
LANGSMITH_TRACING=true       # Enable LangSmith observability
```

## Testing

```bash
pip install -r backend/requirements.txt
pytest
```

Tests cover:
- LangGraph planner routing logic
- Multi-language AST chunking
- Retrieval metric computation
- GitHub URL parsing

## Evaluation

```bash
python evaluation/ragas_eval.py
```

Metrics tracked:
- **Retrieval**: Precision@k, Recall@k, MRR
- **RAG**: Faithfulness, Context Precision/Recall, Answer Relevancy (RAGAS)
- **Performance**: Agent execution time, retrieval latency, LLM latency
- **Cost**: Tokens used, cost per review

## Project Structure

```
backend/
├── app/           # FastAPI application
│   ├── api/       # Route handlers
│   ├── auth/      # GitHub OAuth
│   ├── models/    # SQLAlchemy models
│   ├── schemas/   # Pydantic schemas
│   └── services/  # Business logic
├── agents/        # Specialized review agents
├── graph/         # LangGraph workflow
├── parsers/       # Repo loader, AST chunker
├── vectorstore/   # Qdrant integration
├── tools/         # MCP tool adapters
frontend/          # Next.js UI
evaluation/        # RAGAS evaluation
tests/             # Unit & integration tests
docker/            # Nginx config
```

## Skills Demonstrated

- Multi-agent orchestration with LangGraph
- Retrieval-Augmented Generation (RAG)
- AST-based hierarchical code chunking
- Vector database integration (Qdrant)
- Configurable multi-provider LLM architecture
- MCP tool calling framework
- GitHub OAuth authentication
- PostgreSQL + Redis production data layer
- LangSmith / OpenTelemetry observability
- RAGAS evaluation framework
- Review feedback loop for continuous improvement
- Docker containerization
- Comprehensive test coverage for orchestration logic

## License

MIT
