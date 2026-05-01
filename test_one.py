import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import bot

merchants = json.load(open(ROOT / "dataset" / "merchants_seed.json"))["merchants"]
triggers = json.load(open(ROOT / "dataset" / "triggers_seed.json"))["triggers"]
dentists = json.load(open(ROOT / "dataset" / "categories" / "dentists.json"))

result = bot.compose(dentists, merchants[0], triggers[0], customer=None)
print("BODY:", result["body"])
print("CTA:", result["cta"])