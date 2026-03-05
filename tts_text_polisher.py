import os
import asyncio
from typing import Optional

from freeflow_llm import FreeFlowClient
from freeflow_llm.providers.groq import GroqProvider

TTS_SYSTEM_PROMPT = (
    "You are a professional text editor for speech synthesis. Your task is to take "
    "raw text and transform it so it sounds natural and correct when read aloud by a TTS system.\n\n"
    "Requirements:\n"
    "- Expand contractions (e.g., \"im\" → \"I'm\", \"dont\" → \"don't\", \"its\" → \"it's\").\n"
    "- Fix capitalization so sentences start with a capital letter.\n"
    "- Add proper punctuation (periods, commas, question marks) for natural pauses and phrasing.\n"
    "- Preserve the meaning and intent of the original text.\n"
    "- Return only the polished text — do not add commentary, explanations, or formatting.\n"
    "- Keep it short and concise; only correct and polish the original text.\n"
    "- Do not change the sentence - just fix it with the above requirements."
)


class GitHubModelsProvider(GroqProvider):
    """GitHub Models provider — OpenAI-compatible, uses GH_TTS_TOKEN."""

    def get_api_base_url(self) -> str:
        return "https://models.github.ai/inference/v1"


def _build_providers() -> list:
    """Build the ordered provider list: GitHub → Groq (key 1) → Groq (key 2)."""
    providers = []

    gh_key = os.getenv("GH_TTS_TOKEN", "").strip()
    if gh_key:
        providers.append(GitHubModelsProvider(api_key=gh_key))

    groq_keys = []
    k1 = os.getenv("GROQ_API_KEY", "").strip()
    if k1:
        if "," in k1:
            groq_keys.extend(k.strip() for k in k1.split(",") if k.strip())
        else:
            groq_keys.append(k1)
    k2 = os.getenv("GROQ_API_KEY_2", "").strip()
    if k2:
        groq_keys.append(k2)

    if groq_keys:
        providers.append(GroqProvider(api_key=groq_keys))

    return providers


async def polish_text_for_tts(text: str) -> str:
    """Send *text* through an LLM to fix grammar/punctuation for TTS.

    Returns the polished text, or the original text unchanged if all
    providers fail or no API keys are configured.
    """
    providers = _build_providers()
    if not providers:
        print("[TTS POLISH] No LLM providers configured — returning original text")
        return text

    def _call() -> str:
        with FreeFlowClient(providers=providers, verbose=False) as client:
            response = client.chat(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": TTS_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            return response.content

    try:
        result = await asyncio.to_thread(_call)
        polished = (result or "").strip()
        if polished:
            print(f"[TTS POLISH] OK — {len(text)} chars → {len(polished)} chars")
            return polished
        print("[TTS POLISH] LLM returned empty — using original text")
        return text
    except Exception as exc:
        print(f"[TTS POLISH] Error: {exc} — using original text")
        return text
