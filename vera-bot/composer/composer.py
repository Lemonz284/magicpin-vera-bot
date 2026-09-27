import logging
from typing import Optional
from composer.templates import format_grounded_message
from composer.prompts import build_system_prompt, build_user_prompt
from composer.validator import clean_and_validate_body, is_acceptable_body
from llm.client import LLMClient

logger = logging.getLogger("vera.composer")
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None
) -> dict:
    """
    Main composition function: compose(category, merchant, trigger, customer?)
    1. Generates a 100% grounded deterministic template baseline anchored in the 10 Case Studies.
    2. If an LLM provider is configured, attempts dynamic LLM completion with prompt grounding and validation.
    3. Falls back gracefully to the grounded template baseline if LLM fails, times out, or produces unacceptable output.
    Returns:
        {
            "body": str,
            "cta": str,
            "send_as": str,
            "suppression_key": str,
            "rationale": str,
            "template_name": str,
            "template_params": list[str]
        }
    """
    # 1. Base grounded template
    grounded_res = format_grounded_message(category, merchant, trigger, customer)

    # 2. Attempt LLM enhancement if configured
    try:
        client = get_llm_client()
        if client.is_configured():
            sys_prompt = build_system_prompt(category, merchant)
            user_prompt = build_user_prompt(category, merchant, trigger, customer, grounded_draft=grounded_res.get("body"))

            raw_output = client.complete(user_prompt, system=sys_prompt)
            if raw_output:
                cleaned_body = clean_and_validate_body(raw_output, category, merchant, trigger, customer, grounded_body=grounded_res.get("body"))
                if is_acceptable_body(cleaned_body, category):
                    grounded_res["body"] = cleaned_body
                    grounded_res["rationale"] = f"Composed via {client.provider}:{client.model} with category constraints"
    except Exception as e:
        logger.warning(f"LLM composition failed: {e}. Falling back to grounded template.")

    return grounded_res
