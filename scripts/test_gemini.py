#!/usr/bin/env python3
"""Quick diagnostic: try several Gemini models and report which work."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

models_to_try = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-2.5-flash",
]

for model in models_to_try:
    print(f"\nTrying {model}...")
    try:
        response = client.models.generate_content(
            model=model,
            contents="Say OK.",
        )
        print(f"  SUCCESS: {response.text.strip()}")
    except Exception as e:
        print(f"  FAILED: {e}")

print("\nListing models available to this key:")
try:
    for m in client.models.list():
        print(f"  {m.name}")
except Exception as e:
    print(f"  Could not list models: {e}")
