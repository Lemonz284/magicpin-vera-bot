import os
import json
import sqlite3
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
    """
    ContextStore with hybrid In-Memory + SQLite disk backup.
    Supports continuous in-memory execution and persists state across
    serverless / worker container restarts (e.g. on Vercel /tmp).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.contexts: dict[tuple[str, str], ContextEntry] = {}
        self.conversations: dict[str, Conversation] = {}
        self.suppressed_keys: set[str] = set()
        self.suppressed_merchants: set[str] = set()
        self.merchant_auto_reply_counts: dict[str, int] = {}

        # Determine DB path (fallback to /tmp if available for serverless, else local)
        if db_path:
            self.db_path = db_path
        elif os.path.exists("/tmp"):
            self.db_path = "/tmp/vera_store.db"
        else:
            self.db_path = os.path.join(os.path.dirname(__file__), ".vera_store.db")

        self._init_db()
        self._load_from_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS contexts (
                        scope TEXT,
                        context_id TEXT,
                        version INTEGER,
                        payload TEXT,
                        delivered_at TEXT,
                        stored_at TEXT,
                        PRIMARY KEY (scope, context_id)
                    )
                """)
                conn.execute("CREATE TABLE IF NOT EXISTS suppressions (key TEXT PRIMARY KEY)")
                conn.execute("CREATE TABLE IF NOT EXISTS suppressed_merchants (merchant_id TEXT PRIMARY KEY)")
                conn.commit()
        except Exception:
            pass

    def _load_from_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                for row in cur.execute("SELECT scope, context_id, version, payload, delivered_at, stored_at FROM contexts"):
                    scope, cid, ver, payload_json, del_at, st_at = row
                    self.contexts[(scope, cid)] = ContextEntry(
                        scope=scope,
                        context_id=cid,
                        version=ver,
                        payload=json.loads(payload_json),
                        delivered_at=del_at,
                        stored_at=st_at
                    )
                for (k,) in cur.execute("SELECT key FROM suppressions"):
                    self.suppressed_keys.add(k)
                for (m,) in cur.execute("SELECT merchant_id FROM suppressed_merchants"):
                    self.suppressed_merchants.add(m)
        except Exception:
            pass

    def push_context(self, scope: str, context_id: str, version: int, payload: dict[str, Any], delivered_at: str) -> tuple[bool, int]:
        """Returns (accepted, current_version)."""
        key = (scope, context_id)
        current = self.contexts.get(key)
        if current and current.version >= version:
            return False, current.version

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entry = ContextEntry(
            scope=scope,
            context_id=context_id,
            version=version,
            payload=payload,
            delivered_at=delivered_at,
            stored_at=now_iso
        )
        self.contexts[key] = entry

        # Persist to SQLite
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO contexts (scope, context_id, version, payload, delivered_at, stored_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (scope, context_id, version, json.dumps(payload), delivered_at, now_iso)
                )
                conn.commit()
        except Exception:
            pass

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
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("INSERT OR IGNORE INTO suppressions (key) VALUES (?)", (key,))
                conn.commit()
        except Exception:
            pass

    def is_merchant_suppressed(self, merchant_id: str) -> bool:
        return merchant_id in self.suppressed_merchants

    def suppress_merchant(self, merchant_id: str):
        self.suppressed_merchants.add(merchant_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("INSERT OR IGNORE INTO suppressed_merchants (merchant_id) VALUES (?)", (merchant_id,))
                conn.commit()
        except Exception:
            pass

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

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM contexts")
                conn.execute("DELETE FROM suppressions")
                conn.execute("DELETE FROM suppressed_merchants")
                conn.commit()
        except Exception:
            pass


# Singleton instance shared by the entire application
global_store = ContextStore()
