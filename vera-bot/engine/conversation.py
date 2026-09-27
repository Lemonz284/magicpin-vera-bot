import re
from datetime import datetime, timezone
from typing import Optional
from state.store import ContextStore
from api.schemas import ReplyRequest, ReplyResponse


def handle_merchant_reply(store: ContextStore, req: ReplyRequest) -> ReplyResponse:
    """
    Handles replies from merchant or customer in conversation.
    1. Hostile / Opt-out detection -> graceful end + merchant suppression.
    2. Auto-reply detection -> acknowledge once (send), backoff (wait 86400s), then end.
    3. Off-topic detection -> polite decline and redirect to core business engagement.
    4. Intent transition / commitment -> switch immediately to action delivery without re-qualifying.
    5. Anti-repetition enforcement -> ensures the bot never sends identical text verbatim.
    """
    store.add_turn(req.conversation_id, req.from_role, req.message, req.received_at, req.turn_number)
    conv = store.get_or_create_conversation(req.conversation_id, merchant_id=req.merchant_id or "")

    msg_raw = req.message.strip()
    msg_lower = msg_raw.lower()

    # =========================================================================
    # 1. HOSTILE / OPT-OUT DETECTION
    # =========================================================================
    hostile_phrases = [
        "stop messaging", "not interested", "useless", "spam",
        "bothering me", "stop sending", "leave me alone", "unsubscribe",
        "don't message", "dont message", "harassment", "go away",
        "do not contact", "never message"
    ]
    is_exact_optout = msg_lower in ["stop", "unsubscribe", "optout", "opt-out", "cancel"]
    if is_exact_optout or any(phrase in msg_lower for phrase in hostile_phrases):
        conv.state = "ended"
        if req.merchant_id:
            store.suppress_merchant(req.merchant_id)
        return ReplyResponse(
            action="end",
            rationale="Merchant opted out; closing conversation gracefully"
        )

    # =========================================================================
    # 2. AUTO-REPLY DETECTION
    # =========================================================================
    auto_reply_phrases = [
        "thank you for contacting",
        "our team will respond",
        "automated assistant",
        "automated message",
        "we will get back to you",
        "thanks for reaching out",
        "auto-reply",
        "auto reply",
        "thank you for your message",
        "out of office",
        "currently unavailable",
        "away from desk",
        "busy right now"
    ]
    if any(phrase in msg_lower for phrase in auto_reply_phrases):
        conv.auto_reply_count += 1
        merchant_key = req.merchant_id or req.conversation_id
        merchant_count = store.merchant_auto_reply_counts.get(merchant_key, 0) + 1
        store.merchant_auto_reply_counts[merchant_key] = merchant_count
        effective_count = max(conv.auto_reply_count, merchant_count)

        if effective_count == 1:
            body = "Looks like an auto-reply. Please reply when you have a moment!"
            if body == conv.last_bot_body:
                body = "Noted your automated message. Please feel free to text back when convenient!"
            conv.last_bot_body = body
            now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            store.add_turn(req.conversation_id, "vera", body, now_ts, req.turn_number + 1)
            return ReplyResponse(
                action="send",
                body=body,
                cta="open_ended",
                rationale="Acknowledged auto-reply; asking owner to respond"
            )
        elif effective_count == 2:
            conv.state = "waiting"
            return ReplyResponse(
                action="wait",
                wait_seconds=86400,
                rationale="Detected repeated auto-reply; backing off"
            )
        else:
            conv.state = "ended"
            return ReplyResponse(
                action="end",
                rationale="Detected repeated auto-reply; closing conversation"
            )

    # =========================================================================
    # 3. OFF-TOPIC DETECTION
    # =========================================================================
    off_topic_keywords = [
        "gst", "income tax", "itr", "tax return", "tax filing",
        "accounting", "balance sheet", "tally", "ca firm",
        "weather", "forecast", "cricket score", "ipl score",
        "movie ticket", "train ticket", "flight booking",
        "fix printer", "hardware issue", "wifi down", "repair pc"
    ]
    is_off_topic = any(re.search(r'\b' + re.escape(kw) + r'\b', msg_lower) for kw in off_topic_keywords)
    if is_off_topic:
        body = (
            "I'm dedicated to helping you drive customer visits and revenue on magicpin, "
            "so I'm unable to assist with tax or IT queries. Proceeding back to our business plan: "
            "confirm if you'd like me to send over the next campaign draft."
        )
        if body == conv.last_bot_body:
            body = (
                "My focus is exclusively on your magicpin merchant growth and promotions. "
                "Let's focus on your store: confirm if we should execute the draft we discussed."
            )
        conv.last_bot_body = body
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        store.add_turn(req.conversation_id, "vera", body, now_ts, req.turn_number + 1)
        return ReplyResponse(
            action="send",
            body=body,
            cta="binary_confirm_cancel",
            rationale="Politely declined off-topic query; redirected to core business engagement"
        )

    # =========================================================================
    # 4. COMMITMENT / INTENT TRANSITION
    # =========================================================================
    commitment_phrases = [
        "lets do it", "let's do it", "whats next", "what's next",
        "send the abstract", "proceed", "go ahead", "send me the list",
        "confirm and proceed", "confirm draft", "yes", "sure", "ok",
        "okay", "yes please", "share details", "interested", "do it",
        "sounds good", "ready", "haan", "theek hai"
    ]
    is_commitment = any(phrase in msg_lower for phrase in commitment_phrases)
    if is_commitment:
        conv.state = "action"
        body = "Great! Proceeding with this next. Sending the draft for you to confirm."
        if body == conv.last_bot_body:
            body = "Done! Proceeding immediately. Here is the draft ready for your confirmation."
        conv.last_bot_body = body
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        store.add_turn(req.conversation_id, "vera", body, now_ts, req.turn_number + 1)
        return ReplyResponse(
            action="send",
            body=body,
            cta="binary_confirm_cancel",
            rationale="Merchant explicitly committed; switching from qualifying to action execution."
        )

    # =========================================================================
    # 5. DEFAULT CONVERSATION ADVANCE (Anti-repetition protected)
    # =========================================================================
    body = "Got it! Here is the next step to execute this. Confirm whenever you're ready to proceed."
    if body == conv.last_bot_body:
        body = "Understood. Here is the operational update ready for your confirmation."

    conv.last_bot_body = body
    now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    store.add_turn(req.conversation_id, "vera", body, now_ts, req.turn_number + 1)
    return ReplyResponse(
        action="send",
        body=body,
        cta="binary_confirm_cancel",
        rationale="Acknowledged merchant reply; advancing conversation"
    )
