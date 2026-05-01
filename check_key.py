#!/usr/bin/env python3
"""Run from vera-bot/ folder:  python check_key.py"""
import os, json, urllib.request, urllib.error
from pathlib import Path

print("=== STEP 1: Check .env file ===")
env_path = Path(".env")
if not env_path.exists():
    print("ERROR: .env file not found — are you in the vera-bot/ folder?")
    exit()

text = env_path.read_text(encoding="utf-8-sig")
key = ""
for line in text.splitlines():
    line = line.strip()
    if line.startswith("MISTRAL_API_KEY"):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

if not key:
    print("ERROR: MISTRAL_API_KEY not found in .env")
    print()
    print("Steps to fix:")
    print("  1. Go to https://console.mistral.ai")
    print("  2. Sign up (no credit card needed)")
    print("  3. Go to API Keys -> Create new key")
    print("  4. Add to .env:  MISTRAL_API_KEY=your-key-here")
    exit()

print(f"Key found: {key[:8]}...{key[-4:]} | Length: {len(key)}")
print()

print("=== STEP 2: Test Mistral API ===")
payload = json.dumps({
    "model": "mistral-small-latest",
    "temperature": 0,
    "max_tokens": 20,
    "messages": [{"role": "user", "content": "Reply with only the word: working"}],
}).encode()

req = urllib.request.Request(
    "https://api.mistral.ai/v1/chat/completions",
    data=payload,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
        reply = data["choices"][0]["message"]["content"].strip()
        print(f"SUCCESS! Mistral API key works.")
        print(f"Response: {reply}")
        print()
        print("Now run: python test_one.py")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"FAILED: HTTP {e.code}: {body[:300]}")