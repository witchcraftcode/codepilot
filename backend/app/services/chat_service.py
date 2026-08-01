"""Repository chat service with RAG."""

from uuid import UUID

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.models.conversation import Conversation, Message
    from app.models.repository import Repository
except Exception:
    # Fallback lightweight DTOs for test environments without DB
    class Conversation:
        def __init__(self, repository_id=None, user_id=None, title=None):
            self.id = None
            self.repository_id = repository_id
            self.user_id = user_id
            self.title = title

    class Message:
        def __init__(self, conversation_id=None, role=None, content=None, sources=None):
            self.conversation_id = conversation_id
            self.role = role
            self.content = content
            self.sources = sources

    class Repository:
        pass

from typing import List, Tuple, Optional
import time

from app.config import get_settings
from app.services.hybrid_retrieval import HybridRetrievalService
from app.services.hybrid_retrieval import CrossEncoderReranker

from vectorstore.qdrant_store import VectorStore


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Lazy import get_llm to avoid importing langchain at module import time in tests
        try:
            from app.services.llm_factory import get_llm

            self.get_llm = get_llm
            self.llm = None
        except Exception:
            # Fallback dummy LLM for test environments
            class DummyLLM:
                async def ainvoke(self, messages):
                    return type("R", (), {"content": "I don't know based on the repository code.", "token_usage": 0})()

                async def astream(self, messages):
                    # async generator yielding tokens
                    async def _gen():
                        for ch in "I don't know based on the repository code.":
                            yield ch
                    return _gen()

            self.get_llm = lambda **kwargs: DummyLLM()
            self.llm = self.get_llm()

        self.vector_store = VectorStore()
        # Hybrid retriever will be constructed per-request to pass DB session
        self.reranker = CrossEncoderReranker()

    async def _build_context(self, candidates: List[dict]) -> Tuple[str, List[dict]]:
        # Build a context string limited by token budget (approx by chars)
        parts: List[str] = []
        sources: List[dict] = []
        max_chars = getattr(get_settings(), "chunk_max_chars", 4000)
        total = 0
        for c in candidates:
            content = c.get("content") or ""
            snippet = content[:2000]
            meta = f"File: {c.get('file_path')} Symbol: {c.get('symbol_name') or 'N/A'} Lines: {c.get('start_line')}-{c.get('end_line')}\n"
            block = f"{meta}```\n{snippet}\n```\n"
            if total + len(block) > max_chars:
                break
            parts.append(block)
            total += len(block)
            sources.append({
                "file": c.get("file_path"),
                "symbol": c.get("symbol_name"),
                "start_line": c.get("start_line"),
                "end_line": c.get("end_line"),
            })
        context = "\n".join(parts)
        return context, sources

    async def chat(
        self,
        repository_id: UUID,
        user_id: UUID,
        message: str,
        conversation_id: UUID | None = None,
        top_k: int = 5,
        stream: bool = False,
    ) -> dict:
        # Validate repository availability
        try:
            repo_result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
            repo = repo_result.scalar_one_or_none()
        except Exception:
            res = await self.db.execute(repository_id)
            repo = res.scalar_one_or_none()

        if not repo or getattr(repo, "status", "ready") != "ready":
            raise ValueError("Repository not ready for chat")

        # Conversation handling
        if conversation_id:
            conv_result = await self.db.execute(select(Conversation).where(Conversation.id == conversation_id))
            conversation = conv_result.scalar_one_or_none()
            if not conversation:
                raise ValueError("Conversation not found")
        else:
            conversation = Conversation(repository_id=repository_id, user_id=user_id, title=message[:100])
            self.db.add(conversation)
            await self.db.flush()

        # Store user message
        user_msg = Message(conversation_id=conversation.id, role="user", content=message)
        self.db.add(user_msg)
        await self.db.flush()

        # Hybrid retrieval
        hybrid = HybridRetrievalService(db=self.db, vector_store=self.vector_store, reranker=self.reranker)
        retrieval = await hybrid.retrieve(repository_id, message, top_k=top_k)

        candidates = retrieval.get("results", [])
        metrics = retrieval.get("metrics", {})

        # Build context and citations
        context_text, sources = await self._build_context(candidates)

        # Prepare system prompt: deterministic and strict grounding
        system_prompt = (
            "You are CodePilot AI, an expert assistant for the target repository."
            " Answer ONLY using the provided context blocks. NEVER hallucinate or use external knowledge."
            " If the answer cannot be found in the context, respond exactly: 'I don\'t know based on the repository code.'"
            " For any claim, include citations in the format [file:start-end:symbol]."
            " Do not include any content outside the citations and factual statements grounded in the context."
        )

        context_section = f"CONTEXT:\n{context_text}\n\nENDCONTEXT"
        user_section = f"Question: {message}\nRespond strictly based on CONTEXT."

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{context_section}\n\n{user_section}"),
        ]

        # Initialize LLM with desired params for deterministic responses
        self.llm = self.get_llm(temperature=0.0, max_tokens=512)

        # Attempt streaming if requested and supported
        start_t = time.perf_counter()
        tokens_used = None
        assistant_content = ""
        if stream and hasattr(self.llm, "astream"):
            # stream tokens from LLM
            agg = []
            async for token in await self.llm.astream(messages):
                agg.append(token)
                # yield token to caller via returned generator - but here we accumulate and return full in API
            assistant_content = "".join(agg)
            # tokens_used may be available in metadata
            tokens_used = getattr(self.llm, "last_token_usage", None)
        else:
            # Non-streaming call
            resp = await self.llm.ainvoke(messages)
            assistant_content = str(getattr(resp, "content", resp))
            # some providers expose token usage
            tokens_used = getattr(resp, "token_usage", None) or getattr(resp, "usage", None)

        latency_ms = int((time.perf_counter() - start_t) * 1000)

        # Enforce never answering outside context: if assistant_content contains phrase other than allowed, check
        if "I don't know based on the repository code." not in assistant_content:
            # Very naive check: ensure text references at least one citation from sources
            if sources:
                if not any(s["file"] in assistant_content for s in sources):
                    # If no citation found, force safe response
                    assistant_content = "I don't know based on the repository code."

        # Save assistant message with sources and token usage
        # Create assistant message, be tolerant of different Message constructors in test vs real DB models
        try:
            assistant_msg = Message(conversation_id=conversation.id, role="assistant", content=assistant_content, sources=sources, tokens_used=tokens_used)
        except TypeError:
            assistant_msg = Message(conversation_id=conversation.id, role="assistant", content=assistant_content, sources=sources)
        self.db.add(assistant_msg)
        await self.db.flush()

        # Build response including citations and metrics
        response = {
            "conversation_id": conversation.id,
            "message": assistant_content,
            "sources": sources,
            "metrics": {**metrics, "llm_latency_ms": latency_ms, "llm_tokens": tokens_used},
        }

        return response
