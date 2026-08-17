"""
Thin wrapper around the Google Gemini API for the advisor layer.

Uses the Google GenAI SDK (`google-genai`, imported as `from google import genai`),
which is the stable GA library for the Gemini Developer API.

Requires GEMINI_API_KEY (or GOOGLE_API_KEY) set in your environment or a .env
file. Get a key at https://aistudio.google.com/app/apikey

The public functions (ask, ask_with_history) keep the same signatures as the
previous Anthropic version, so prompts.py, app.py and notify.py need no changes.
"""
import os
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load .env from the project root explicitly, regardless of the current
# working directory streamlit/python was launched from.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

# Pick a current Gemini model. Google rotates these periodically and retires
# old ones for new users, so this is read from the GEMINI_MODEL env var if set,
# falling back to a current default. If you get a 404 "no longer available"
# error, update this default or set GEMINI_MODEL in your .env to the model the
# error message suggests.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        expected_path = Path(__file__).resolve().parent.parent / ".env"
        raise EnvironmentError(
            f"GEMINI_API_KEY not set. Create a file at exactly this path:\n"
            f"  {expected_path}\n"
            f"containing one line (no quotes, no spaces around =):\n"
            f"  GEMINI_API_KEY=your-key-here\n"
            f"Get a key at https://aistudio.google.com/app/apikey"
        )
    return genai.Client(api_key=api_key)


def ask(prompt: str, max_tokens: int = 800) -> str:
    """Single-turn call. Used by explain_forecast, explain_allocation, and the chat panel."""
    client = _client()
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    return resp.text


def ask_with_history(messages: list[dict], max_tokens: int = 800) -> str:
    """
    Multi-turn call for the chat panel. messages is a list of
    {"role": "user"|"assistant", "content": str} dicts — the same shape the
    Anthropic version used, so app.py doesn't need to change.

    Gemini uses role "model" instead of "assistant" and nests text under
    "parts", so we translate here.
    """
    client = _client()

    gemini_contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        gemini_contents.append({"role": role, "parts": [{"text": m["content"]}]})

    resp = client.models.generate_content(
        model=MODEL,
        contents=gemini_contents,
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    return resp.text
