import httpx
import json
import time

BASE_URL = "http://localhost:8080"
client = httpx.Client(base_url=BASE_URL, timeout=10)

def test_all():
    ts = int(time.time())

    print("=== 1. Healthz ===")
    r = client.get("/v1/healthz")
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "contexts_loaded" in r.json()

    print("\n=== 2. Metadata ===")
    r = client.get("/v1/metadata")
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["team_name"] == "Vera Bot"

    print("\n=== 3. Context Push (valid v1) ===")
    cat_id = f"test_cat_{ts}"
    payload = {
        "scope": "category",
        "context_id": cat_id,
        "version": 1,
        "payload": {"slug": cat_id, "voice": {"tone": "peer_clinical"}},
        "delivered_at": "2026-04-26T10:00:00Z"
    }
    r = client.post("/v1/context", json=payload)
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert "ack_id" in r.json()

    print("\n=== 4. Context Push (duplicate v1 -> 409) ===")
    r = client.post("/v1/context", json=payload)
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 409
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "stale_version"

    print("\n=== 5. Context Push (higher version v2 -> 200) ===")
    payload["version"] = 2
    r = client.post("/v1/context", json=payload)
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    print("\n=== 6. Context Push (invalid scope -> 400) ===")
    bad_payload = dict(payload)
    bad_payload["scope"] = "invalid_scope"
    r = client.post("/v1/context", json=bad_payload)
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 400
    assert r.json()["accepted"] is False

    print("\n=== 7. Healthz Context Count Check ===")
    r = client.get("/v1/healthz")
    print("Status:", r.status_code, "Body:", r.json())
    assert r.json()["contexts_loaded"]["category"] >= 1

    print("\n=== 8. Tick with empty triggers ===")
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": []})
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["actions"] == []

    print("\n=== 9. Tick with active trigger ===")
    mid = f"m_test_{ts}"
    tid = f"trg_test_{ts}"
    # Push category, merchant and trigger
    merchant_payload = {
        "scope": "merchant",
        "context_id": mid,
        "version": 1,
        "payload": {
            "merchant_id": mid,
            "category_slug": cat_id,
            "identity": {"name": "Dr. Meera's Clinic", "owner_first_name": "Meera"}
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    }
    client.post("/v1/context", json=merchant_payload)

    trigger_payload = {
        "scope": "trigger",
        "context_id": tid,
        "version": 1,
        "payload": {
            "id": tid,
            "merchant_id": mid,
            "kind": "research_digest",
            "suppression_key": f"suppress_{tid}",
            "scope": "merchant"
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    }
    client.post("/v1/context", json=trigger_payload)

    r = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": [tid]})
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert len(r.json()["actions"]) == 1
    action = r.json()["actions"][0]
    assert action["merchant_id"] == mid
    assert "Meera" in action["body"]

    print("\n=== 10. Reply (engaged response) ===")
    reply_body = {
        "conversation_id": f"conv_engaged_{ts}",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Yes please send the abstract",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    }
    r = client.post("/v1/reply", json=reply_body)
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["action"] == "send"

    print("\n=== 11. Reply (Auto-reply handling: send -> wait -> end) ===")
    auto_reply = {
        "conversation_id": f"conv_auto_{ts}",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    }
    # Turn 1 of auto-reply
    r1 = client.post("/v1/reply", json=auto_reply)
    print("Auto-reply 1 action:", r1.json()["action"])
    assert r1.json()["action"] == "send"

    # Turn 2 of auto-reply
    auto_reply["turn_number"] = 3
    r2 = client.post("/v1/reply", json=auto_reply)
    print("Auto-reply 2 action:", r2.json()["action"])
    assert r2.json()["action"] == "wait"
    assert r2.json()["wait_seconds"] == 86400

    # Turn 3 of auto-reply
    auto_reply["turn_number"] = 4
    r3 = client.post("/v1/reply", json=auto_reply)
    print("Auto-reply 3 action:", r3.json()["action"])
    assert r3.json()["action"] == "end"

    print("\n=== 12. Reply (Hostile handling -> end) ===")
    hostile = {
        "conversation_id": f"conv_hostile_{ts}",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    }
    r = client.post("/v1/reply", json=hostile)
    print("Status:", r.status_code, "Body:", r.json())
    assert r.status_code == 200
    assert r.json()["action"] == "end"

    print("\n ALL TESTS PASSED SUCCESSFULLY! ")

if __name__ == "__main__":
    test_all()
