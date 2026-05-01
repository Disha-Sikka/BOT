#!/usr/bin/env python3
"""Debug script to test Groq API connection."""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

# Load .env
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _val.strip())

api_key = os.environ.get("GROQ_API_KEY", "")
print(f"API Key loaded: {api_key[:20]}..." if api_key else "No API key")
print()

payload = {
    "model": "llama-3.3-70b-versatile",
    "temperature": 0,
    "max_tokens": 100,
    "messages": [
        {"role": "user", "content": "Hello, test message"},
    ],
}

print("Sending test request to Groq API...")
print(f"Model: {payload['model']}")
print(f"Endpoint: https://api.groq.com/openai/v1/chat/completions")
print()

req = urllib.request.Request(
    "https://api.groq.com/openai/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read())
        print("✓ SUCCESS")
        print(data["choices"][0]["message"]["content"])
except urllib.error.HTTPError as e:
    print(f"✗ HTTP Error {e.code}")
    error_body = e.read().decode()
    print(f"Response:\n{error_body}")
    try:
        err_json = json.loads(error_body)
        print(f"\nParsed error: {json.dumps(err_json, indent=2)}")
    except:
        pass
except Exception as e:
    print(f"✗ Exception: {type(e).__name__}: {e}")
