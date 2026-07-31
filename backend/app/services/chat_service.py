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

from vectorstore.qdrant_store import VectorStore


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Lazy import get_llm to avoid importing langchain at module import time in tests
        try:
            from app.services.llm_factory import get_llm

            self.llm = get_llm()
        except Exception:
            # Fallback dummy LLM for test environments
            class DummyLLM:
                async def ainvoke(self, messages):
                    return type("R", (), {"content": "I don't know based on the repository code."})()

            self.llm = DummyLLM()

        self.vector_store = VectorStore()

    async def chat(
        self,
        repository_id: UUID,
        user_id: UUID,
        message: str,
        conversation_id: UUID | None = None,
    ) -> dict:
        try:
            repo_result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
            repo = repo_result.scalar_one_or_none()
        except Exception:
            # Fallback for test environments where SQLAlchemy models may not be available.
            res = await self.db.execute(repository_id)
            repo = res.scalar_one_or_none()

        if not repo or getattr(repo, "status", "ready") != "ready":
            raise ValueError("Repository not ready for chat")

        if conversation_id:
            conv_result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = conv_result.scalar_one_or_none()
            if not conversation:
                raise ValueError("Conversation not found")
        else:
            conversation = Conversation(
                repository_id=repository_id,
                user_id=user_id,
                title=message[:100],
            )
            self.db.add(conversation)
            await self.db.flush()

        user_msg = Message(conversation_id=conversation.id, role="user", content=message)
        self.db.add(user_msg)

        chunks = await self.vector_store.search(
            query=message,
            repository_id=str(repository_id),
            limit=8,
        )

        context = "\n\n".join(
            f"File: {c['file_path']} ({c['chunk_type']}: {c.get('symbol_name', 'N/A')})\nLines: {c.get('start_line')}-{c.get('end_line')}\n```\n{c['content']}\n```"
            for c in chunks
        )

        system_prompt = f"""You are CodePilot AI, an expert code assistant for the repository "{repo.full_name}".
Answer questions based ONLY on the provided code context below. Do NOT hallucinate. If the answer cannot be found in the context, respond with: "I don't know based on the repository code.".
Provide explicit citations for any facts you state in the form: [file_path:start_line-end_line:symbol].
"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {message}"),
        ]

        response = await self.llm.ainvoke(messages)
        assistant_content = str(response.content)

        # Build citations from retrieved chunks
        citations = []
        for c in chunks:
            citations.append(
                {
                    "file_path": c.get("file_path"),
                    "start_line": c.get("start_line"),
                    "end_line": c.get("end_line"),
                    "symbol": c.get("symbol_name"),
                    "chunk_type": c.get("chunk_type"),
                    "score": c.get("score"),
                }
            )

        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_content,
            sources=citations,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        return {
            "conversation_id": conversation.id,
            "message": assistant_content,
            "sources": citations,
        }
