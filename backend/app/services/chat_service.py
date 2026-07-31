"""Repository chat service with RAG."""

from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.repository import Repository
from app.services.llm_factory import get_llm
from vectorstore.qdrant_store import VectorStore


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm()
        self.vector_store = VectorStore()

    async def chat(
        self,
        repository_id: UUID,
        user_id: UUID,
        message: str,
        conversation_id: UUID | None = None,
    ) -> dict:
        repo_result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repo = repo_result.scalar_one_or_none()
        if not repo or repo.status != "ready":
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
            f"File: {c['file_path']} ({c['chunk_type']}: {c.get('symbol_name', 'N/A')})\n```\n{c['content']}\n```"
            for c in chunks
        )

        system_prompt = f"""You are CodePilot AI, an expert code assistant for the repository "{repo.full_name}".
Answer questions based ONLY on the provided code context. Cite specific files and functions.
If you cannot find relevant code, say so clearly."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {message}"),
        ]

        response = await self.llm.ainvoke(messages)
        assistant_content = str(response.content)

        sources = [
            {
                "file_path": c["file_path"],
                "chunk_type": c["chunk_type"],
                "symbol_name": c.get("symbol_name"),
                "relevance_score": c["score"],
            }
            for c in chunks
        ]

        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_content,
            sources=sources,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        return {
            "conversation_id": conversation.id,
            "message": assistant_content,
            "sources": sources,
        }
