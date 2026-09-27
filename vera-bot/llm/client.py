import os
import json
import logging
from typing import Optional
import httpx
from config import LLM_PROVIDER, LLM_API_KEY, LLM_MODEL

logger = logging.getLogger("vera.llm")


class LLMClient:
    """
    Multi-provider LLM client for message composition.
    Supports OpenAI, Gemini, Anthropic, Groq, OpenRouter, and Ollama.
    Falls back gracefully to None on timeouts or missing credentials.
    """

    def __init__(
        self,
        provider: str = LLM_PROVIDER,
        api_key: str = LLM_API_KEY,
        model: str = LLM_MODEL,
        timeout_seconds: float = 12.0
    ):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "openai")).lower()
        self.api_key = api_key or self._detect_api_key(self.provider)
        self.model = model or self._default_model_for_provider(self.provider)
        self.timeout = timeout_seconds
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    def _detect_api_key(self, provider: str) -> str:
        key = os.getenv("LLM_API_KEY", "")
        if key:
            return key
        if provider == "openai":
            return os.getenv("OPENAI_API_KEY", "")
        elif provider == "gemini":
            return os.getenv("GOOGLE_GENAI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        elif provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY", "")
        elif provider == "groq":
            return os.getenv("GROQ_API_KEY", "")
        elif provider == "openrouter":
            return os.getenv("OPENROUTER_API_KEY", "")
        return ""

    def _default_model_for_provider(self, provider: str) -> str:
        defaults = {
            "openai": "gpt-4o-mini",
            "gemini": "gemini-1.5-flash",
            "anthropic": "claude-3-5-haiku-20241022",
            "groq": "openai/gpt-oss-120b",
            "openrouter": "openai/gpt-4o-mini",
            "ollama": "llama3",
        }
        return defaults.get(provider, "gpt-4o-mini")

    def is_configured(self) -> bool:
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def complete(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """
        Sends completion request to configured LLM provider.
        Returns generated text or None if unconfigured / failed.
        """
        if not self.is_configured():
            return None

        try:
            if self.provider == "openai":
                return self._complete_openai(prompt, system)
            elif self.provider == "gemini":
                return self._complete_gemini(prompt, system)
            elif self.provider == "anthropic":
                return self._complete_anthropic(prompt, system)
            elif self.provider == "groq":
                return self._complete_groq(prompt, system)
            elif self.provider == "openrouter":
                return self._complete_openrouter(prompt, system)
            elif self.provider == "ollama":
                return self._complete_ollama(prompt, system)
            else:
                logger.warning(f"Unknown LLM provider: {self.provider}")
                return None
        except Exception as e:
            logger.warning(f"LLM completion error ({self.provider}): {e}")
            return None

    def _complete_openai(self, prompt: str, system: Optional[str]) -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 400
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            logger.warning(f"OpenAI error {resp.status_code}: {resp.text}")
            return None

    def _complete_gemini(self, prompt: str, system: Optional[str]) -> Optional[str]:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400}
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    return candidates[0]["content"]["parts"][0]["text"].strip()
            logger.warning(f"Gemini error {resp.status_code}: {resp.text}")
            return None

    def _complete_anthropic(self, prompt: str, system: Optional[str]) -> Optional[str]:
        with httpx.Client(timeout=self.timeout) as client:
            payload = {
                "model": self.model,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2
            }
            if system:
                payload["system"] = system

            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["content"][0]["text"].strip()
            logger.warning(f"Anthropic error {resp.status_code}: {resp.text}")
            return None

    def _complete_groq(self, prompt: str, system: Optional[str]) -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 400
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            return None

    def _complete_openrouter(self, prompt: str, system: Optional[str]) -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://magicpin.com"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 400
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            return None

    def _complete_ollama(self, prompt: str, system: Optional[str]) -> Optional[str]:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": 0.2}
                }
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
            return None


# Global LLMClient instance
default_llm_client = LLMClient()
