#!/usr/bin/env python3
"""Diagnostic: try several Gemini models, report success or the exact quota/limit in the error."""
import os
import re
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
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
]

for model in models_to_try:
    print(f"\n{model}...")
    try:
        response = client.models.generate_content(model=model, contents="Say OK.")
        print(f"  SUCCESS: {response.text.strip()}")
    except Exception as e:
        msg = str(e)
        quota_matches = re.findall(r"quotaId': '([^']+)'.*?quotaValue': '(\d+)'", msg)
        if quota_matches:
            for quota_id, value in quota_matches:
                print(f"  LIMIT: {quota_id} = {value}")
        else:
            print(f"  FAILED: {msg[:200]}")
