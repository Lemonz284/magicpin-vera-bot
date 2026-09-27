"""
Prompt generation module for LLM-based message composition.
Enforces MagicPin Vera Challenge scoring guidelines:
- Zero URLs (strict -3 penalty per URL)
- Zero fabricated facts, numbers, or unverified perks (-2 penalty per fake claim)
- Category-specific tone, salutations, allowed and taboo vocabulary
- Respectful single low-friction CTA
- Hinglish code-mix when appropriate
"""

from typing import Optional


def build_system_prompt(category: dict, merchant: dict) -> str:
    category_slug = category.get("slug", "")
    voice = category.get("voice", {})
    tone = voice.get("tone", "professional, warm, helpful")
    allowed_vocab = voice.get("vocab_allowed", [])
    taboo_vocab = voice.get("vocab_taboo", [])
    languages = merchant.get("identity", {}).get("languages", ["en"])

    lang_instruction = ""
    if "hi" in languages:
        lang_instruction = (
            "- Merchant prefers Hindi/English mix (Hinglish). Use natural Indian English with tasteful "
            "conversational Hinglish touchpoints where appropriate (e.g. 'Aapke clinic ke liye...', 'Kya hum ise...')."
        )
    else:
        lang_instruction = "- Use clear, professional, warm Indian English."

    dentist_salutation = ""
    if category_slug == "dentists":
        dentist_salutation = (
            "- For dentists, ALWAYS address the owner as 'Dr. {FirstName}'. Never use casual first names without 'Dr.'.\n"
            "- Strictly NO cartoonish emojis (no 🦷, no ✨). Maintain serious, respectful, peer_clinical professionalism."
        )

    allowed_str = ", ".join(allowed_vocab[:10]) if allowed_vocab else "professional business terms"
    taboo_str = ", ".join(taboo_vocab[:15]) if taboo_vocab else "misleading claims, guaranteed, 100%"

    return f"""You are Vera, an intelligent WhatsApp messaging assistant for local merchants on magicpin in India.
Your mission is to compose concise, highly engaging, and contextually grounded WhatsApp messages.

CRITICAL RULES AND PENALTY WARNINGS:
1. STRICTLY NO URLS: Do NOT include ANY web links, http://, https://, www, or domain names under any circumstance. Including a URL results in an immediate -3 penalty.
2. STRICTLY GROUNDED FACTS & ZERO UNVERIFIED PERKS:
   - Only state numbers, stats, intervals, and offers explicitly provided in the context.
   - NEVER invent complimentary perks, free services, or bonuses (e.g. DO NOT invent 'free fluoride', 'complimentary polish', 'free consult') unless explicitly written in the input context.
   - Check dates and intervals carefully (e.g., if context says 6_month_cleaning, say 6-month, never 5-month).
3. CATEGORY VOICE & TONE:
   - Category: {category_slug}
   - Tone: {tone}
   {dentist_salutation}
   - Preferred vocabulary: {allowed_str}
   - STRICTLY FORBIDDEN / TABOO WORDS: {taboo_str}. Never use these words!
{lang_instruction}
4. HIGH-ENGAGEMENT CALL TO ACTION (CTA) AT THE VERY END:
   - ALWAYS end the message with an explicit, compelling question offering a concrete artifact that Vera does for them (Effort Externalization: e.g. "Want me to draft an audit checklist for your SOPs?", "Should I prepare a 1-click patient broadcast for you?", "Want me to pull the 2-minute clinical summary?").
   - Pair with an ultra low-friction reply ask (e.g. "Reply YES to confirm" or "Reply 1 or 2").
   - NEVER omit the closing question or leave a vague CTA.
5. CONCISE FORMAT:
   - 2 to 3 sentences maximum.
   - Clean WhatsApp messaging format without markdown headers or bullet points.
   - Output ONLY the message text.
"""


def build_user_prompt(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    grounded_draft: Optional[str] = None
) -> str:
    category_slug = category.get("slug", "")
    identity = merchant.get("identity", {})
    owner_name = identity.get("owner_first_name") or identity.get("name") or "Merchant"
    merchant_name = identity.get("name") or "the business"
    locality = identity.get("locality") or identity.get("city") or "your area"

    if category_slug == "dentists" and "dr." not in owner_name.lower():
        salutation_name = f"Dr. {owner_name}"
    else:
        salutation_name = owner_name

    perf = merchant.get("performance", {})
    offers = merchant.get("offers", [])
    active_offers = [o for o in offers if o.get("status") == "active"]

    trigger_kind = trigger.get("kind", "")
    trigger_scope = trigger.get("scope", "merchant")
    trg_payload = trigger.get("payload", {})

    prompt_lines = [
        f"Compose a WhatsApp message for this scenario:",
        f"- Recipient: {salutation_name} ({merchant_name} in {locality})",
        f"- Category: {category_slug}",
        f"- Trigger Kind: {trigger_kind}",
        f"- Target Audience: {'Customer' if trigger_scope == 'customer' else 'Merchant'}",
    ]

    if active_offers:
        prompt_lines.append(f"- Active Merchant Offer: {active_offers[0].get('title', '')}")

    if perf:
        views = perf.get("views")
        calls = perf.get("calls")
        if views is not None:
            prompt_lines.append(f"- 30-Day Views: {views}")
        if calls is not None:
            prompt_lines.append(f"- 30-Day Calls: {calls}")

    if trg_payload:
        prompt_lines.append(f"- Trigger Context Data: {trg_payload}")

    if customer and trigger_scope == "customer":
        cust_identity = customer.get("identity", {})
        cust_name = cust_identity.get("name", "Valued Customer")
        prompt_lines.append(f"- Customer Name: {cust_name}")
        cust_loyalty = customer.get("loyalty", {})
        if cust_loyalty:
            prompt_lines.append(f"- Customer Loyalty: {cust_loyalty.get('tier', '')}, visits: {cust_loyalty.get('total_visits', 0)}")

    if grounded_draft:
        prompt_lines.append(
            f"\nVerified Grounded Reference Draft:\n\"{grounded_draft}\"\n"
            f"Instruction: You may refine this draft for natural flow, but preserve ALL facts, dates, intervals, and prices exactly. "
            f"DO NOT add any unverified perks or change numbers."
        )

    prompt_lines.append(
        "\nRemember: Output ONLY the message body. No URLs. Single low-friction CTA at the end. Zero unverified perks."
    )

    return "\n".join(prompt_lines)
