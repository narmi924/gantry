"""Clients for Microsoft Foundry models and Azure AI Speech.

Both sign in with Microsoft Entra ID (your Azure CLI login locally, a managed
identity in Azure), so no keys live in code or config.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

SCOPE = "https://cognitiveservices.azure.com/.default"


def setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Set {name} in backend/.env (see .env.example)")
    return value


@lru_cache(maxsize=1)
def credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


@lru_cache(maxsize=1)
def models() -> OpenAI:
    """OpenAI-compatible client for models deployed in the Foundry resource."""
    endpoint = setting("AZURE_AI_ENDPOINT").rstrip("/")
    return OpenAI(base_url=f"{endpoint}/openai/v1/", api_key=get_bearer_token_provider(credential(), SCOPE))


def speech_config():
    import azure.cognitiveservices.speech as speechsdk

    return speechsdk.SpeechConfig(token_credential=credential(), endpoint=setting("AZURE_AI_ENDPOINT"))
