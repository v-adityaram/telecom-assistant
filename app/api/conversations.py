import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import conversation_store

router = APIRouter()


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str | None = None


class ConversationDetail(BaseModel):
    id: str
    messages: list[dict]


@router.get("/api/conversations", response_model=list[ConversationSummary])
async def list_conversations(mobile_number: str) -> list[ConversationSummary]:
    items = await asyncio.to_thread(conversation_store.list_conversations, mobile_number)
    return [
        ConversationSummary(id=i["id"], title=i.get("title") or "New conversation", updated_at=i.get("updatedAt"))
        for i in items
    ]


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, mobile_number: str) -> ConversationDetail:
    doc = await asyncio.to_thread(conversation_store.get_conversation, conversation_id, mobile_number)
    if doc is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return ConversationDetail(id=doc["id"], messages=doc.get("messages") or [])
