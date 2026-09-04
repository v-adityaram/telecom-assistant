import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from azure.cosmos import CosmosClient, exceptions

from app.config import get_settings

logger = logging.getLogger("telecom_assistant.conversation_store")


@lru_cache
def _container():
    """Cosmos container client, or None if persistence isn't configured — every
    function below degrades to a no-op/empty result rather than raising, so
    chat/voice work identically whether or not F-004 is set up."""
    settings = get_settings()
    if not settings.cosmos_connection_string:
        return None
    client = CosmosClient.from_connection_string(settings.cosmos_connection_string)
    database = client.get_database_client(settings.cosmos_database)
    return database.get_container_client(settings.cosmos_container)


def is_enabled() -> bool:
    return _container() is not None


def upsert_conversation(conversation_id: str, mobile_number: str, messages: list, title: Optional[str] = None) -> None:
    container = _container()
    if container is None:
        return
    doc = {
        "id": conversation_id,
        "mobileNumber": mobile_number,
        "title": title or (messages[0]["content"][:60] if messages else "New conversation"),
        "messages": messages,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    container.upsert_item(doc)


def get_conversation(conversation_id: str, mobile_number: str) -> Optional[dict]:
    container = _container()
    if container is None:
        return None
    try:
        return container.read_item(item=conversation_id, partition_key=mobile_number)
    except exceptions.CosmosResourceNotFoundError:
        return None


def list_conversations(mobile_number: str, limit: int = 50) -> list:
    container = _container()
    if container is None:
        return []
    query = (
        "SELECT c.id, c.title, c.updatedAt FROM c WHERE c.mobileNumber = @mobileNumber "
        "ORDER BY c.updatedAt DESC OFFSET 0 LIMIT @limit"
    )
    params = [{"name": "@mobileNumber", "value": mobile_number}, {"name": "@limit", "value": limit}]
    return list(container.query_items(query=query, parameters=params, partition_key=mobile_number))


def delete_conversation(conversation_id: str, mobile_number: str) -> None:
    container = _container()
    if container is None:
        return
    try:
        container.delete_item(item=conversation_id, partition_key=mobile_number)
    except exceptions.CosmosResourceNotFoundError:
        pass
