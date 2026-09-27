import pytest
from fastapi.testclient import TestClient
from main import app
from state.store import global_store
from composer.validator import clean_and_validate_body, is_acceptable_body

client = TestClient(app)

def setup_function():
    global_store.clear()

def test_healthz_initial():
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}

def test_metadata():
    r = client.get("/v1/metadata")
    assert r.status_code == 200
    data = r.json()
    assert data["team_name"] == "Vera Bot"
    assert data["team_members"] == ["Builder"]
    assert data["version"] == "1.0.0"
    assert "submitted_at" in data

def test_context_push_and_versioning():
    # 1. First push
    payload = {
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {"slug": "dentists", "voice": {"tone": "peer_clinical"}},
        "delivered_at": "2026-04-26T10:00:00Z"
    }
    r = client.post("/v1/context", json=payload)
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert r.json()["ack_id"] == "ack_dentists_v1"

    # 2. Duplicate / lower version -> 409
    r_dup = client.post("/v1/context", json=payload)
    assert r_dup.status_code == 409
    assert r_dup.json()["accepted"] is False
    assert r_dup.json()["reason"] == "stale_version"
    assert r_dup.json()["current_version"] == 1

    # 3. Higher version -> 200
    payload["version"] = 2
    r_v2 = client.post("/v1/context", json=payload)
    assert r_v2.status_code == 200
    assert r_v2.json()["accepted"] is True
    assert r_v2.json()["ack_id"] == "ack_dentists_v2"

    # 4. Invalid scope -> 400
    bad_scope_payload = dict(payload)
    bad_scope_payload["scope"] = "unsupported_scope"
    r_bad = client.post("/v1/context", json=bad_scope_payload)
    assert r_bad.status_code == 400
    assert r_bad.json()["accepted"] is False
    assert r_bad.json()["reason"] == "invalid_scope"
    assert r_bad.json()["details"] == "scope must be one of: category, merchant, customer, trigger"

    # 5. Check healthz count
    r_hz = client.get("/v1/healthz")
    assert r_hz.json()["contexts_loaded"]["category"] == 1

def test_tick_and_suppression():
    # Push category, merchant, trigger
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1,
        "payload": {
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "category_slug": "dentists",
            "identity": {"owner_first_name": "Meera", "name": "Dr. Meera's Clinic"}
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_001_research_digest_dentists", "version": 1,
        "payload": {
            "id": "trg_001_research_digest_dentists",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "kind": "research_digest",
            "scope": "merchant",
            "suppression_key": "research:dentists:2026-W17"
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })

    # Empty triggers
    r_empty = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": []})
    assert r_empty.status_code == 200
    assert r_empty.json()["actions"] == []

    # Active trigger
    r_tick = client.post("/v1/tick", json={
        "now": "2026-04-26T10:30:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    })
    assert r_tick.status_code == 200
    actions = r_tick.json()["actions"]
    assert len(actions) == 1
    act = actions[0]
    assert act["conversation_id"] == "conv_m_001_drmeera_dentist_delhi_trg_001_research_digest_dentists"
    assert act["merchant_id"] == "m_001_drmeera_dentist_delhi"
    assert act["customer_id"] is None
    assert act["send_as"] == "vera"
    assert act["trigger_id"] == "trg_001_research_digest_dentists"
    assert "research_digest" in act["template_name"]
    assert "Dr. Meera" in act["body"]
    assert "http" not in act["body"]
    assert act["cta"] == "open_ended"
    assert act["suppression_key"] == "research:dentists:2026-W17"

    # Second tick with same trigger should be suppressed
    r_tick_2 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    })
    assert r_tick_2.json()["actions"] == []

def test_expiry_filtering():
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1,
        "payload": {
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "category_slug": "dentists",
            "identity": {"owner_first_name": "Meera", "name": "Dr. Meera's Clinic"}
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })
    # Expired trigger: expires_at is before now
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_expired", "version": 1,
        "payload": {
            "id": "trg_expired",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "kind": "research_digest",
            "scope": "merchant",
            "expires_at": "2026-04-26T09:00:00Z"
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })

    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:30:00Z",
        "available_triggers": ["trg_expired"]
    })
    assert r.status_code == 200
    assert len(r.json()["actions"]) == 0

def test_priority_ranking_single_trigger_per_merchant():
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1,
        "payload": {
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "category_slug": "dentists",
            "identity": {"owner_first_name": "Meera", "name": "Dr. Meera's Clinic"}
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })
    # Low priority trigger: research_digest (base 40)
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_low", "version": 1,
        "payload": {
            "id": "trg_low",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "kind": "research_digest",
            "scope": "merchant"
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })
    # High priority trigger: urgent_review_alert (base 100)
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_high", "version": 1,
        "payload": {
            "id": "trg_high",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "kind": "urgent_review_alert",
            "scope": "merchant",
            "rating": 1,
            "sentiment": "negative"
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })

    # Both available for the same merchant -> exactly 1 action, and it should be trg_high
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:30:00Z",
        "available_triggers": ["trg_low", "trg_high"]
    })
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["trigger_id"] == "trg_high"

def test_validation_url_and_taboo_stripping():
    category = {
        "slug": "dentists",
        "voice": {
            "vocab_taboo": ["guaranteed", "miracle", "cheap", "100% cure"]
        }
    }
    merchant = {
        "identity": {"owner_first_name": "Meera", "name": "Dr. Meera Clinic"}
    }
    trigger = {"scope": "merchant"}

    raw = "Dr. Meera, this guaranteed miracle treatment is available now at cheap rates! Visit https://magicpin.in/treatments today."
    cleaned = clean_and_validate_body(raw, category, merchant, trigger)

    assert "https://" not in cleaned
    assert "magicpin.in" not in cleaned
    assert "guaranteed" not in cleaned.lower()
    assert "miracle" not in cleaned.lower()
    assert "cheap" not in cleaned.lower()
    assert is_acceptable_body(cleaned, category) is True

def test_reply_conversations():
    # Engaged reply
    r_reply = client.post("/v1/reply", json={
        "conversation_id": "conv_001",
        "merchant_id": "m_001",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Yes please",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    })
    assert r_reply.status_code == 200
    assert r_reply.json()["action"] == "send"
    assert "proceeding" in r_reply.json()["body"].lower()
    assert r_reply.json()["cta"] == "binary_confirm_cancel"

    # Auto-reply 1 -> send
    r_auto_1 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto",
        "merchant_id": "m_002",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    })
    assert r_auto_1.status_code == 200
    assert r_auto_1.json()["action"] == "send"

    # Auto-reply 2 -> wait 86400s
    r_auto_2 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto",
        "merchant_id": "m_002",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-04-26T10:50:00Z",
        "turn_number": 3
    })
    assert r_auto_2.status_code == 200
    assert r_auto_2.json()["action"] == "wait"
    assert r_auto_2.json()["wait_seconds"] == 86400

    # Auto-reply 3 -> end
    r_auto_3 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto",
        "merchant_id": "m_002",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-04-26T10:55:00Z",
        "turn_number": 4
    })
    assert r_auto_3.status_code == 200
    assert r_auto_3.json()["action"] == "end"

    # Hostile reply -> end
    r_hostile = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile",
        "merchant_id": "m_003",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    })
    assert r_hostile.status_code == 200
    assert r_hostile.json()["action"] == "end"
    assert r_hostile.json()["rationale"] == "Merchant opted out; closing conversation gracefully"
    assert global_store.is_merchant_suppressed("m_003") is True

def test_off_topic_reply_handling():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_offtopic",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Can you help me file my GST tax return?",
        "received_at": "2026-04-26T11:00:00Z",
        "turn_number": 2
    })
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    assert "magicpin" in data["body"]
    assert "tax" in data["body"]
    assert data["cta"] == "binary_confirm_cancel"
    assert "off-topic" in data["rationale"].lower()

def test_commitment_action_mode():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_commit",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "received_at": "2026-04-26T11:00:00Z",
        "turn_number": 2
    })
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    # Action mode keywords must be present
    body_lower = data["body"].lower()
    assert any(w in body_lower for w in ["done", "sending", "draft", "confirm", "proceed", "next"])
    # Qualifying questions must not be present
    assert not any(w in body_lower for w in ["would you", "do you want", "can you tell", "what if"])
    assert data["cta"] == "binary_confirm_cancel"

def test_anti_repetition_guard():
    # Turn 2
    r1 = client.post("/v1/reply", json={
        "conversation_id": "conv_repeat",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Okay",
        "received_at": "2026-04-26T11:00:00Z",
        "turn_number": 2
    })
    assert r1.status_code == 200
    body1 = r1.json()["body"]

    # Turn 4 with same intent
    r2 = client.post("/v1/reply", json={
        "conversation_id": "conv_repeat",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Okay",
        "received_at": "2026-04-26T11:05:00Z",
        "turn_number": 4
    })
    assert r2.status_code == 200
    body2 = r2.json()["body"]

    # Verify anti-repetition altered the text
    assert body1 != body2

