from datetime import datetime, timezone
from typing import Optional, Any
from state.store import ContextStore
from api.schemas import ActionItem
from composer.composer import compose


PRIORITY_BY_KIND: dict[str, float] = {
    # High urgency / critical threats (100 - 80)
    "urgent_review_alert": 100.0,
    "negative_review": 100.0,
    "rating_drop": 95.0,
    "slot_occupancy_drop": 90.0,
    "cart_abandonment": 85.0,
    "customer_churn_risk": 85.0,
    "competitive_threat": 80.0,
    # High value retention / reactivation (75 - 70)
    "lapsed_patient_reactivation": 75.0,
    "lapsed_client_winback": 75.0,
    "lapsed_member_winback": 75.0,
    "chronic_refill_due": 75.0,
    "seasonal_demand_spike": 70.0,
    "festival_demand_surge": 70.0,
    "seasonal_flu_surge": 70.0,
    # Upsells & Revenue boosts (60)
    "high_margin_service_push": 60.0,
    "hair_skin_combo_upsell": 60.0,
    "off_peak_table_filling": 60.0,
    "personal_training_upsell": 60.0,
    "first_aid_kit_upsell": 60.0,
    # Care & Follow-ups (55)
    "post_treatment_checkin": 55.0,
    "post_service_care": 55.0,
    "trial_session_followup": 55.0,
    "rx_adherence_checkin": 55.0,
    # Informational / Digests (40)
    "research_digest": 40.0,
    "category_seasonal": 40.0,
}


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        clean = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        return None


def is_expired(expires_at: Optional[str], now_str: Optional[str]) -> bool:
    """Returns True if expires_at is strictly in the past relative to now_str."""
    if not expires_at or not now_str:
        return False
    exp_dt = parse_iso_datetime(expires_at)
    now_dt = parse_iso_datetime(now_str)
    if exp_dt and now_dt:
        return exp_dt < now_dt
    return False


def calculate_priority(trg_payload: dict, now_str: Optional[str] = None) -> float:
    """Calculates a numerical ranking score for a candidate trigger."""
    kind = trg_payload.get("kind", "")
    score = PRIORITY_BY_KIND.get(kind, 50.0)

    # 1. Explicit priority attribute
    prio = trg_payload.get("priority")
    if isinstance(prio, (int, float)):
        score += float(prio) * 10
    elif isinstance(prio, str):
        prio_lower = prio.lower()
        if prio_lower in ("critical", "urgent"):
            score += 50.0
        elif prio_lower == "high":
            score += 30.0
        elif prio_lower == "medium":
            score += 10.0
        elif prio_lower == "low":
            score -= 10.0

    # 2. Urgency level
    urg = trg_payload.get("urgency", "")
    if isinstance(urg, str):
        urg_lower = urg.lower()
        if urg_lower == "immediate":
            score += 40.0
        elif urg_lower == "today":
            score += 20.0

    # 3. Expiry proximity boost (boost triggers expiring soon)
    expires_at = trg_payload.get("expires_at")
    if expires_at and now_str:
        exp_dt = parse_iso_datetime(expires_at)
        now_dt = parse_iso_datetime(now_str)
        if exp_dt and now_dt:
            diff_hours = (exp_dt - now_dt).total_seconds() / 3600.0
            if 0 < diff_hours <= 24:
                score += 25.0
            elif 0 < diff_hours <= 48:
                score += 15.0

    return score


def _get_nested(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    if isinstance(data.get("payload"), dict):
        for key in keys:
            if key in data["payload"] and data["payload"][key] is not None:
                return data["payload"][key]
    return None


def select_and_build_actions(store: ContextStore, available_triggers: list[str], now: str) -> list[ActionItem]:
    """
    Selects valid, unsuppressed, non-expired triggers and builds proactive outbound actions.
    Enforces:
    1. Valid context resolution (trigger, merchant, category, customer).
    2. Expiry validation (expires_at >= now).
    3. Suppression key checking.
    4. Single-trigger per merchant per tick (highest priority chosen).
    5. Prioritization ranking across merchants.
    6. Max 20 actions cap per tick.
    7. Message composition grounded in context with category voice & validation.
    """
    candidates_by_merchant: dict[str, list[tuple[float, str, dict, dict, dict, Optional[dict]]]] = {}

    for trigger_id in available_triggers:
        trg_entry = store.get_context("trigger", trigger_id)
        if not trg_entry:
            continue
        trg_payload = trg_entry.payload

        # 1. Expiry check
        expires_at = _get_nested(trg_payload, "expires_at")
        if expires_at and is_expired(expires_at, now):
            continue

        # 2. Merchant resolution
        merchant_id = _get_nested(trg_payload, "merchant_id")
        if not merchant_id or store.is_merchant_suppressed(merchant_id):
            continue

        merchant_entry = store.get_context("merchant", merchant_id)
        if not merchant_entry:
            continue
        merchant_payload = merchant_entry.payload

        # 3. Category resolution
        category_slug = _get_nested(merchant_payload, "category_slug")
        if not category_slug:
            continue
        category_entry = store.get_context("category", category_slug)
        if not category_entry:
            continue
        category_payload = category_entry.payload

        # 4. Suppression key check
        suppression_key = _get_nested(trg_payload, "suppression_key")
        if not suppression_key:
            kind = _get_nested(trg_payload, "kind") or "update"
            suppression_key = f"{kind}:{merchant_id}"
        if store.is_suppressed(suppression_key):
            continue

        # 5. Customer resolution if customer-scoped (graceful optional lookup)
        customer_id = _get_nested(trg_payload, "customer_id")
        customer_payload = None
        if customer_id:
            customer_entry = store.get_context("customer", customer_id)
            if customer_entry:
                customer_payload = customer_entry.payload
            elif isinstance(trg_payload.get("customer"), dict):
                customer_payload = trg_payload.get("customer")

        # Compute priority score
        score = calculate_priority(trg_payload, now)

        if merchant_id not in candidates_by_merchant:
            candidates_by_merchant[merchant_id] = []
        candidates_by_merchant[merchant_id].append(
            (score, trigger_id, trg_payload, merchant_payload, category_payload, customer_payload)
        )

    # For each merchant, pick the single highest-priority trigger
    best_per_merchant: list[tuple[float, str, dict, dict, dict, Optional[dict]]] = []
    for merchant_id, candidates in candidates_by_merchant.items():
        candidates.sort(key=lambda c: c[0], reverse=True)
        best_per_merchant.append(candidates[0])

    # Rank across merchants by priority score descending
    best_per_merchant.sort(key=lambda c: c[0], reverse=True)

    # Cap at 20 actions
    selected = best_per_merchant[:20]

    actions: list[ActionItem] = []
    for score, trigger_id, trg_payload, merchant_payload, category_payload, customer_payload in selected:
        merchant_id = _get_nested(trg_payload, "merchant_id")
        customer_id = _get_nested(trg_payload, "customer_id")

        # Compose message
        composed = compose(category_payload, merchant_payload, trg_payload, customer_payload)

        body = composed["body"]
        cta = composed["cta"]
        send_as = composed["send_as"]
        suppression_key = composed["suppression_key"]
        rationale = composed["rationale"]
        template_name = composed.get("template_name", "vera_grounded_v1")
        template_params = composed.get("template_params", [])

        conversation_id = f"conv_{merchant_id}_{trigger_id}"

        action = ActionItem(
            conversation_id=conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            send_as=send_as,
            trigger_id=trigger_id,
            template_name=template_name,
            template_params=template_params,
            body=body,
            cta=cta,
            suppression_key=suppression_key,
            rationale=rationale
        )

        # Update store state
        store.suppress(suppression_key)
        store.create_conversation(conversation_id, merchant_id, customer_id, trigger_id)
        now_ts = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        store.add_turn(conversation_id, send_as, body, now_ts, 1)
        conv = store.get_conversation(conversation_id)
        if conv:
            conv.last_bot_body = body

        actions.append(action)

    return actions
