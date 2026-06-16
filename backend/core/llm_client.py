import os
import json
import time
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from dotenv import load_dotenv

load_dotenv()

_client = None
MODEL = "gemini-flash-lite-latest"


class DailyQuotaExhausted(Exception):
    """Raised when the Gemini free-tier per-day request quota is hit."""


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _call(prompt: str, json_mode: bool, retries: int = 2):
    config = types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    for attempt in range(retries + 1):
        try:
            return get_client().models.generate_content(model=MODEL, contents=prompt, config=config)
        except ClientError as e:
            if "PerDay" in str(e):
                raise DailyQuotaExhausted(str(e)) from e
            raise
        except ServerError:
            if attempt == retries:
                raise
            time.sleep(2 * (attempt + 1))


def generate_json(prompt: str) -> dict:
    response = _call(prompt, json_mode=True)
    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError):
        return {}


def generate_text(prompt: str) -> str:
    response = _call(prompt, json_mode=False)
    return (response.text or "").strip()
