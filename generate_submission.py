#!/usr/bin/env python3
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

BASE = os.path.dirname(os.path.abspath(__file__))
merchants_raw = json.load(open(f"{BASE}/dataset/merchants_seed.json"))["merchants"]
customers_raw = json.load(open(f"{BASE}/dataset/customers_seed.json"))["customers"]
triggers_raw  = json.load(open(f"{BASE}/dataset/triggers_seed.json"))["triggers"]

categories = {}
for slug in ["dentists","gyms","salons","pharmacies","restaurants"]:
    categories[slug] = json.load(open(f"{BASE}/dataset/categories/{slug}.json"))

merchants = {m["merchant_id"]: m for m in merchants_raw}
customers  = {c["customer_id"]: c for c in customers_raw}
triggers   = {t["id"]: t for t in triggers_raw}

def run(test_id, trigger_id):
    trg = triggers[trigger_id]
    mid = trg.get("merchant_id") or trg.get("payload",{}).get("merchant_id")
    merchant = merchants[mid]
    cat = categories[merchant["category_slug"]]
    customer = customers.get(trg.get("customer_id")) if trg.get("customer_id") else None
    result = bot.compose(cat, merchant, trg, customer)
    return {"test_id": test_id, **result}

records = []
for i, trg in enumerate(triggers_raw, 1):
    tid = f"T{i:02d}"
    print(f"[{tid}] {trg['kind']}...", flush=True)
    try:
        rec = run(tid, trg["id"])
        records.append(rec)
        print(f"  OK: {rec['body'][:80]}...")
    except Exception as e:
        print(f"  ERROR: {e}")
        records.append({"test_id":tid,"body":f"[ERROR:{e}]","cta":"open_ended",
                        "send_as":"vera","suppression_key":trg.get("suppression_key",tid),"rationale":"error"})

for tid, trgid in [("T26","trg_003_recall_due_priya"),("T27","trg_007_bridal_followup_kavya"),
                   ("T28","trg_015_winback_rashmi"),("T29","trg_017_kids_yoga_trial_followup_karthik"),
                   ("T30","trg_019_chronic_refill_grandfather")]:
    print(f"[{tid}] {trgid}...", flush=True)
    try:
        rec = run(tid, trgid)
        records.append(rec)
        print(f"  OK: {rec['body'][:80]}...")
    except Exception as e:
        print(f"  ERROR: {e}")

with open(f"{BASE}/submission.jsonl","w",encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec,ensure_ascii=False)+"\n")
print(f"\nDone — {len(records)} records written to submission.jsonl")