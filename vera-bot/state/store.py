from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime, timezone


@dataclass
class ContextEntry:
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str
    stored_at: str


@dataclass
class ConversationTurn:
    role: str          # "vera", "merchant", "customer", etc.
    body: str
    timestamp: str
    turn_number: int


@dataclass
class Conversation:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    trigger_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    state: str = "active"           # active, waiting, ended
    auto_reply_count: int = 0
    last_bot_body: Optional[str] = None  # for anti-repetition


class ContextStore:
    def __init__(self):
        self.contexts: dict[tuple[str, str], ContextEntry] = {}
        self.conversations: dict[str, Conversation] = {}
        self.suppressed_keys: set[str] = set()
        self.suppressed_merchants: set[str] = set()
        self.merchant_auto_reply_counts: dict[str, int] = {}

    def push_context(self, scope: str, context_id: str, version: int, payload: dict[str, Any], delivered_at: str) -> tuple[bool, int]:
        """Returns (accepted, current_version)."""
        key = (scope, context_id)
        current = self.contexts.get(key)
        if current and current.version >= version:
            return False, current.version
        self.contexts[key] = ContextEntry(
            scope=scope,
            context_id=context_id,
            version=version,
            payload=payload,
            delivered_at=delivered_at,
            stored_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return True, version

    def get_context(self, scope: str, context_id: str) -> Optional[ContextEntry]:
        return self.contexts.get((scope, context_id))

    def get_payload(self, scope: str, context_id: str) -> Optional[dict]:
        entry = self.get_context(scope, context_id)
        return entry.payload if entry else None

    def count_by_scope(self) -> dict[str, int]:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _) in self.contexts:
            counts[scope] = counts.get(scope, 0) + 1
        return counts

    def is_suppressed(self, key: str) -> bool:
        return key in self.suppressed_keys

    def suppress(self, key: str):
        self.suppressed_keys.add(key)

    def is_merchant_suppressed(self, merchant_id: str) -> bool:
        return merchant_id in self.suppressed_merchants

    def suppress_merchant(self, merchant_id: str):
        self.suppressed_merchants.add(merchant_id)

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        return self.conversations.get(conversation_id)

    def create_conversation(self, conversation_id: str, merchant_id: str, customer_id: Optional[str], trigger_id: str) -> Conversation:
        conv = Conversation(
            conversation_id=conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            trigger_id=trigger_id
        )
        self.conversations[conversation_id] = conv
        return conv

    def get_or_create_conversation(self, conversation_id: str, merchant_id: str = "", customer_id: Optional[str] = None, trigger_id: str = "") -> Conversation:
        conv = self.conversations.get(conversation_id)
        if not conv:
            conv = Conversation(
                conversation_id=conversation_id,
                merchant_id=merchant_id,
                customer_id=customer_id,
                trigger_id=trigger_id
            )
            self.conversations[conversation_id] = conv
        return conv

    def add_turn(self, conversation_id: str, role: str, body: str, timestamp: str, turn_number: int):
        conv = self.get_or_create_conversation(conversation_id)
        conv.turns.append(ConversationTurn(role=role, body=body, timestamp=timestamp, turn_number=turn_number))

    def clear(self):
        """Wipe all stored state (used by /v1/teardown)."""
        self.contexts.clear()
        self.conversations.clear()
        self.suppressed_keys.clear()
        self.suppressed_merchants.clear()
        self.merchant_auto_reply_counts.clear()


# Singleton instance shared by the entire application
global_store = ContextStore()
