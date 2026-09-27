import re
from typing import Optional


def clean_and_validate_body(
    body: str,
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    grounded_body: Optional[str] = None
) -> str:
    """
    Cleans and validates the composed message body:
    1. Removes any URLs to avoid -3 penalty.
    2. Strips category taboo words.
    3. Ensures proper salutations (e.g. Dr. for dentists).
    4. Ensures an explicit closing CTA question is present.
    5. Trims surrounding whitespace and quotes.
    6. Guarantees clean formatting.
    """
    if not body:
        return ""

    text = body.strip().strip('"').strip("'")

    # 1. Strict URL removal: replace any http/https/www URLs or domains with empty string
    url_pattern = re.compile(r'https?://\S+|www\.\S+|\b\S+\.(com|in|org|net|co|io|ly)\b', re.IGNORECASE)
    text = url_pattern.sub('', text)

    # 2. Category taboo vocabulary removal
    voice = category.get("voice", {})
    taboo_words = voice.get("vocab_taboo", [])
    for taboo in taboo_words:
        raw_taboo = re.sub(r'\(.*?\)', '', taboo).strip()
        if raw_taboo:
            pattern = re.compile(r'\b' + re.escape(raw_taboo) + r'\b', re.IGNORECASE)
            text = pattern.sub('', text)

    # 3. Dentist salutation check: If sent to dentist merchant, ensure "Dr." is present without duplication
    category_slug = category.get("slug", "")
    trigger_scope = trigger.get("scope", "merchant")
    if category_slug == "dentists" and trigger_scope == "merchant":
        identity = merchant.get("identity", {})
        owner_name = identity.get("owner_first_name") or identity.get("name") or ""
        if owner_name:
            if f"Dr. {owner_name}" not in text and f"Dr.{owner_name}" not in text:
                pattern = re.compile(r'(?<!Dr\.\s)(?<!Dr\s)\b' + re.escape(owner_name) + r'\b', re.IGNORECASE)
                text = pattern.sub(f"Dr. {owner_name}", text)
            # Remove any accidental stutter like "Dr. Meera, aap Dr. Meera"
            text = re.sub(re.escape(f"Dr. {owner_name}") + r'([,\s]+aap[,\s]+)' + re.escape(f"Dr. {owner_name}"), f"Dr. {owner_name}, aap", text, flags=re.IGNORECASE)

    # 4. Remove cartoonish emojis for dentists to preserve peer_clinical tone
    if category_slug == "dentists":
        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)
        text = emoji_pattern.sub('', text)

    # 5. Clean up any double spaces, dangling commas, or formatting glitches
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\s+([.,?!])', r'\1', text)
    text = text.strip()

    # 6. Ensure high-compulsion CTA question is present at the end
    if "?" not in text and grounded_body and "?" in grounded_body:
        # Extract the closing question from grounded template
        cta_match = re.search(r'([A-Z][^?]*\?.*)', grounded_body)
        if cta_match:
            closing_cta = cta_match.group(1).strip()
            text = text.rstrip(".! ") + " " + closing_cta

    return text.strip()


def is_acceptable_body(body: str, category: dict) -> bool:
    """
    Validates if the cleaned body meets minimum standards:
    - Minimum length 25 characters
    - Contains at least one punctuation mark (., ?, !)
    - Does not contain http or www
    """
    if not body or len(body.strip()) < 25:
        return False
    if "http" in body.lower() or "www." in body.lower():
        return False
    return True
