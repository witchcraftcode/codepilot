"""Base agent class with RAG retrieval and structured output."""

import json
import time
import uuid
from abc import ABC, abstractmethod

try:
    from langchain_core.messages import HumanMessage, SystemMessage
except Exception:
    # Lightweight fallback message wrappers for environments without langchain
    class HumanMessage:
        def __init__(self, content: str):
            self.content = content

    class SystemMessage:
        def __init__(self, content: str):
            self.content = content

from app.services.llm_factory import get_llm
from app.services.observability import extract_token_usage, measured_llm_ainvoke
from graph.state import AgentFinding, AgentResult, ReviewState
from vectorstore.qdrant_store import VectorStore


class BaseAgent(ABC):
    name: str = "base"
    description: str = ""
    default_queries: list[str] = []

    def __init__(self) -> None:
        # Initialize lazily to avoid importing provider libs during tests
        try:
            self._llm = None
        except Exception:
            self._llm = None
        self.vector_store = VectorStore()

    async def _ensure_llm(self):
        if getattr(self, "_llm", None) is None:
            try:
                self._llm = get_llm()
            except Exception:
                # Fallback dummy LLM
                class _D:
                    async def ainvoke(self, messages):
                        return type("R", (), {"content": "{}"})()

                self._llm = _D()

    @abstractmethod
    def get_system_prompt(self) -> str:
        pass

    def get_retrieval_queries(self, state: ReviewState) -> list[str]:
        return self.default_queries

    async def retrieve_context(self, state: ReviewState) -> list[dict]:
        queries = self.get_retrieval_queries(state)
        all_results: list[dict] = []
        seen: set[str] = set()

        for query in queries:
            results = await self.vector_store.search(
                query=query,
                repository_id=state["repository_id"],
                limit=5,
            )
            for r in results:
                key = f"{r['file_path']}:{r.get('symbol_name', '')}"
                if key not in seen:
                    seen.add(key)
                    all_results.append(r)

        return all_results[:15]

    def format_context(self, chunks: list[dict]) -> str:
        if not chunks:
            return "No relevant code found."
        parts = []
        for i, chunk in enumerate(chunks, 1):
            parts.append(
                f"--- Chunk {i} ({chunk['chunk_type']}: {chunk.get('symbol_name', 'N/A')}) ---\n"
                f"File: {chunk['file_path']}\n"
                f"```{chunk.get('language', '')}\n{chunk['content']}\n```"
            )
        return "\n\n".join(parts)

    async def run(self, state: ReviewState) -> AgentResult:
        start = time.time()
        context_chunks = await self.retrieve_context(state)
        context_text = self.format_context(context_chunks)

        metadata = state.get("repo_metadata", {})
        user_msg = f"""Analyze this repository for {self.name} concerns.

Repository metadata:
- Languages: {metadata.get('languages', {})}
- Frameworks: {metadata.get('frameworks', [])}
- File count: {metadata.get('file_count', 0)}

User request: {state.get('user_request', 'Full review')}

Relevant code:
{context_text}

Respond with JSON only:
{{
  "score": <0-100>,
  "summary": "<brief summary>",
  "findings": [
    {{
      "severity": "critical|high|medium|low|info",
      "category": "<category>",
      "title": "<title>",
      "description": "<description>",
      "file_path": "<path or null>",
      "line_number": <number or null>,
      "suggestion": "<fix suggestion>"
    }}
  ]
}}"""

        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(content=user_msg),
        ]

        await self._ensure_llm()
        response, _, observed_tokens, _ = await measured_llm_ainvoke(self._llm, messages, operation=f"agent.{self.name}")
        duration_ms = int((time.time() - start) * 1000)

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            parsed = json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            parsed = {
                "score": 50,
                "summary": str(response.content)[:500],
                "findings": [],
            }

        findings: list[AgentFinding] = []
        for f in parsed.get("findings", []):
            findings.append(
                AgentFinding(
                    id=str(uuid.uuid4()),
                    severity=f.get("severity", "info"),
                    category=f.get("category", self.name),
                    title=f.get("title", "Finding"),
                    description=f.get("description", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    suggestion=f.get("suggestion"),
                )
            )

        tokens_used = observed_tokens or extract_token_usage(response) or len(str(response.content)) // 4

        return AgentResult(
            agent_name=self.name,
            score=parsed.get("score"),
            findings=findings,
            summary=parsed.get("summary", ""),
            tokens_used=tokens_used,
            duration_ms=duration_ms,
        )
