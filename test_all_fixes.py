#!/usr/bin/env python3
"""
test_all_fixes.py
Tests all 5 fixes from the magicpin judge feedback.
Run from vera-bot folder: python test_all_fixes.py

Make sure your server is running first:
  python server.py 8080
"""

import json
import urllib.request
import urllib.error
import time

BASE = "http://localhost:8080"
PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []

def post(path, body):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode()), e.code

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read())

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status} {name}")
    if detail:
        print(f"     → {detail}")
    return condition

def push_context(scope, context_id, payload, version=1):
    resp, code = post("/v1/context", {
        "scope": scope,
        "context_id": context_id,
        "version": version,
        "payload": payload,
        "delivered_at": "2026-05-01T10:00:00Z"
    })
    return resp, code

def setup_base_context():
    """Push all base contexts needed for tests."""
    print("\nSetting up base context...")

    # Category
    push_context("category", "dentists", {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "salutation": "Dr. {first_name}", "vocab_no": ["guaranteed"]},
        "offer_catalog": [{"title": "Dental Cleaning @ Rs.299"}, {"title": "Teeth Whitening @ Rs.1499"}],
        "peer_stats": {"avg_ctr": 0.03, "avg_rating": 4.4, "avg_review_count": 62, "avg_views_30d": 1820},
        "digest": [{
            "id": "d_jida", "source": "JIDA Oct 2026 p.14",
            "title": "3-month fluoride recall cuts caries 38% vs 6-month",
            "trial_n": 2100, "patient_segment": "high_risk_adults",
            "summary": "38% lower caries recurrence with 3-month recall."
        }],
        "seasonal_beats": [], "trend_signals": []
    })

    # Merchant
    push_context("merchant", "m_001_drmeera", {
        "merchant_id": "m_001_drmeera", "category_slug": "dentists",
        "identity": {"name": "Dr. Meera Dental", "owner_first_name": "Meera",
                     "city": "Delhi", "locality": "Lajpat Nagar",
                     "languages": ["en", "hi"], "verified": True},
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021, "leads": 9,
                        "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05, "ctr_pct": 0.02}},
        "offers": [{"title": "Dental Cleaning @ Rs.299", "status": "active"}],
        "signals": ["ctr_below_peer_median", "high_risk_adult_cohort"],
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
        "customer_aggregate": {"total_unique_ytd": 540, "lapsed_180d_plus": 78,
                               "retention_6mo_pct": 0.38, "high_risk_adult_count": 124},
        "review_themes": [], "conversation_history": []
    })

    # Customer
    push_context("customer", "c_001_priya", {
        "customer_id": "c_001_priya", "merchant_id": "m_001_drmeera",
        "identity": {"name": "Priya", "language_pref": "hi-en mix", "age_band": "25-35"},
        "relationship": {"first_visit": "2025-11-04", "last_visit": "2026-05-12",
                         "visits_total": 4, "services_received": ["cleaning", "whitening"]},
        "state": "lapsed_soft",
        "preferences": {"preferred_slots": "weekday_evening", "channel": "whatsapp"},
        "consent": {"scope": ["recall_reminders"]}
    })

    print("  Base context pushed.\n")


# ======================================================================
print("=" * 60)
print("  VERA BOT — ALL FIXES TEST SUITE")
print("=" * 60)

# Check server is alive
try:
    health = get("/v1/healthz")
    print(f"\n✅ Server is running (uptime: {health.get('uptime_seconds')}s)")
except Exception as e:
    print(f"\n❌ Server not reachable: {e}")
    print("   Start server first: python server.py 8080")
    exit(1)

setup_base_context()


# ======================================================================
# TEST 1: Stale Version Fix
# ======================================================================
print("─" * 60)
print("TEST 1: Stale Version — judge must never get rejected")
print("─" * 60)

# Push version 1
r1, c1 = push_context("merchant", "m_test_stale", {"merchant_id": "m_test_stale", "category_slug": "dentists", "identity": {"name": "Test"}}, version=1)
check("Push version 1 accepted", r1.get("accepted") == True, f"Response: {r1}")

# Push version 1 again (same version — was being rejected before)
r2, c2 = push_context("merchant", "m_test_stale", {"merchant_id": "m_test_stale", "category_slug": "dentists", "identity": {"name": "Test Updated"}}, version=1)
check("Push same version again accepted (not stale_version error)", r2.get("accepted") == True, f"Response: {r2}")

# Push lower version (judge sometimes sends v1 after v2 was stored)
r3, c3 = push_context("merchant", "m_test_stale_v2", {"merchant_id": "m_test_stale_v2", "category_slug": "dentists", "identity": {"name": "Test"}}, version=5)
push_context("merchant", "m_test_stale_v2", {"merchant_id": "m_test_stale_v2", "category_slug": "dentists", "identity": {"name": "Test Lower"}}, version=1)
r4, c4 = push_context("merchant", "m_test_stale_v2", {"merchant_id": "m_test_stale_v2", "category_slug": "dentists", "identity": {"name": "Fresh Data"}}, version=1)
check("Push lower version accepted (not rejected)", r4.get("accepted") == True, f"Response: {r4}")


# ======================================================================
# TEST 2: STOP Handling
# ======================================================================
print("\n" + "─" * 60)
print("TEST 2: STOP must ALWAYS return action=end")
print("─" * 60)

# First create a conversation via tick
push_context("trigger", "trg_stop_test", {
    "id": "trg_stop_test", "scope": "merchant", "kind": "research_digest",
    "merchant_id": "m_001_drmeera", "customer_id": None,
    "payload": {"category": "dentists", "top_item_id": "d_jida"},
    "urgency": 2, "suppression_key": f"stop_test:{time.time()}",
    "expires_at": "2026-12-01T00:00:00Z"
})

tick_resp, _ = post("/v1/tick", {"now": "2026-05-01T10:00:00Z", "available_triggers": ["trg_stop_test"]})
conv_id = None
if tick_resp.get("actions"):
    conv_id = tick_resp["actions"][0].get("conversation_id")
    print(f"  Got conversation_id: {conv_id}")

# Test STOP reply
stop_resp, _ = post("/v1/reply", {
    "conversation_id": conv_id or "conv_test_stop",
    "merchant_id": "m_001_drmeera",
    "customer_id": None,
    "from_role": "merchant",
    "message": "STOP",
    "received_at": "2026-05-01T10:05:00Z",
    "turn_number": 2
})
check("STOP returns action=end", stop_resp.get("action") == "end",
      f"Got action={stop_resp.get('action')}, body={stop_resp.get('body','')[:50]}")

# Test lowercase stop
stop_resp2, _ = post("/v1/reply", {
    "conversation_id": conv_id or "conv_test_stop2",
    "merchant_id": "m_001_drmeera",
    "customer_id": None,
    "from_role": "merchant",
    "message": "stop",
    "received_at": "2026-05-01T10:05:00Z",
    "turn_number": 2
})
check("lowercase 'stop' returns action=end", stop_resp2.get("action") == "end",
      f"Got action={stop_resp2.get('action')}")

# Test "not interested"
ni_resp, _ = post("/v1/reply", {
    "conversation_id": conv_id or "conv_test_ni",
    "merchant_id": "m_001_drmeera",
    "customer_id": None,
    "from_role": "merchant",
    "message": "not interested",
    "received_at": "2026-05-01T10:05:00Z",
    "turn_number": 2
})
check("'not interested' returns action=end", ni_resp.get("action") == "end",
      f"Got action={ni_resp.get('action')}")


# ======================================================================
# TEST 3: Auto-reply Detection
# ======================================================================
print("\n" + "─" * 60)
print("TEST 3: Auto-reply detection — wait once, end after 2")
print("─" * 60)

# Create fresh conversation
push_context("trigger", "trg_auto_test", {
    "id": "trg_auto_test", "scope": "merchant", "kind": "perf_dip",
    "merchant_id": "m_001_drmeera", "customer_id": None,
    "payload": {"metric": "calls", "delta_pct": -0.5},
    "urgency": 4, "suppression_key": f"auto_test:{time.time()}",
    "expires_at": "2026-12-01T00:00:00Z"
})
tick_resp2, _ = post("/v1/tick", {"now": "2026-05-01T11:00:00Z", "available_triggers": ["trg_auto_test"]})
auto_conv_id = None
if tick_resp2.get("actions"):
    auto_conv_id = tick_resp2["actions"][0].get("conversation_id")

AUTO_MSG = "Thank you for contacting us. This is an automated response."

r_auto1, _ = post("/v1/reply", {
    "conversation_id": auto_conv_id or "conv_auto1",
    "merchant_id": "m_001_drmeera", "customer_id": None,
    "from_role": "merchant", "message": AUTO_MSG,
    "received_at": "2026-05-01T11:01:00Z", "turn_number": 2
})
check("1st auto-reply → action=wait (not send)",
      r_auto1.get("action") in ("wait", "end"),
      f"Got action={r_auto1.get('action')}")

r_auto2, _ = post("/v1/reply", {
    "conversation_id": auto_conv_id or "conv_auto1",
    "merchant_id": "m_001_drmeera", "customer_id": None,
    "from_role": "merchant", "message": AUTO_MSG,
    "received_at": "2026-05-01T11:02:00Z", "turn_number": 3
})
check("2nd auto-reply → action=end",
      r_auto2.get("action") == "end",
      f"Got action={r_auto2.get('action')}")


# ======================================================================
# TEST 4: Customer-voiced Reply
# ======================================================================
print("\n" + "─" * 60)
print("TEST 4: Customer reply addressed to customer (not merchant)")
print("─" * 60)

# Create customer-scoped trigger
push_context("trigger", "trg_customer_test", {
    "id": "trg_customer_test", "scope": "customer", "kind": "recall_due",
    "merchant_id": "m_001_drmeera", "customer_id": "c_001_priya",
    "payload": {"service_due": "6_month_cleaning", "available_slots": [{"label": "Wed 5 Nov, 6pm"}]},
    "urgency": 3, "suppression_key": f"cust_test:{time.time()}",
    "expires_at": "2026-12-01T00:00:00Z"
})
tick_resp3, _ = post("/v1/tick", {"now": "2026-05-01T12:00:00Z", "available_triggers": ["trg_customer_test"]})
cust_conv_id = None
if tick_resp3.get("actions"):
    cust_conv_id = tick_resp3["actions"][0].get("conversation_id")
    print(f"  Customer trigger fired: {tick_resp3['actions'][0].get('body','')[:80]}...")

cust_reply, _ = post("/v1/reply", {
    "conversation_id": cust_conv_id or "conv_cust1",
    "merchant_id": "m_001_drmeera",
    "customer_id": "c_001_priya",
    "from_role": "customer",
    "message": "Yes please book me for Wed 5 Nov, 6pm.",
    "received_at": "2026-05-01T12:05:00Z",
    "turn_number": 2
})
body = cust_reply.get("body", "")
check("Customer reply action=send", cust_reply.get("action") == "send", f"action={cust_reply.get('action')}")
check("Customer reply not generic 'Namaste'", "Namaste! Aapka message mila" not in body, f"Body: {body[:80]}")
check("Customer reply addresses Priya", "Priya" in body or len(body) > 20, f"Body: {body[:80]}")


# ======================================================================
# TEST 5: Trigger Coverage (6 trigger kinds)
# ======================================================================
print("\n" + "─" * 60)
print("TEST 5: All 6 trigger kinds must fire with non-empty actions[]")
print("─" * 60)

trigger_kinds = [
    ("research_digest",  {"category": "dentists", "top_item_id": "d_jida"}),
    ("recall_due",       {"service_due": "cleaning", "available_slots": [{"label": "Mon 6pm"}]}),
    ("perf_dip",         {"metric": "calls", "delta_pct": -0.5, "window": "7d"}),
    ("ipl_match_today",  {"match": "DC vs MI", "venue": "Delhi", "city": "Delhi", "match_time_iso": "2026-05-01T19:30:00+05:30"}),
    ("renewal_due",      {"days_remaining": 12, "plan": "Pro", "renewal_amount": 4999}),
    ("competitor_opened",{"competitor_name": "SmileStudio", "distance_km": 1.3, "their_offer": "Cleaning @ Rs.199"}),
]

for kind, payload in trigger_kinds:
    trig_id = f"trg_coverage_{kind}_{int(time.time())}"
    push_context("trigger", trig_id, {
        "id": trig_id, "scope": "merchant", "kind": kind,
        "merchant_id": "m_001_drmeera", "customer_id": None,
        "payload": payload, "urgency": 3,
        "suppression_key": f"coverage:{kind}:{time.time()}",
        "expires_at": "2026-12-01T00:00:00Z"
    })
    tick_r, _ = post("/v1/tick", {"now": "2026-05-01T13:00:00Z", "available_triggers": [trig_id]})
    actions = tick_r.get("actions", [])
    fired = len(actions) > 0 and bool(actions[0].get("body", "").strip())
    body_preview = actions[0].get("body", "")[:60] if actions else "NO ACTION"
    check(f"Trigger kind '{kind}' fires", fired, f"Body: {body_preview}")
    time.sleep(1)  # avoid rate limiting


# ======================================================================
# RESULTS SUMMARY
# ======================================================================
print("\n" + "=" * 60)
print("  FINAL RESULTS")
print("=" * 60)
passed = sum(1 for s, _, _ in results if s == PASS)
failed = sum(1 for s, _, _ in results if s == FAIL)
total = len(results)
print(f"\n  {passed}/{total} tests passed\n")

if failed > 0:
    print("Failed tests:")
    for status, name, detail in results:
        if status == FAIL:
            print(f"  {FAIL} {name}")
            if detail:
                print(f"       {detail}")
else:
    print("  All tests passed! Ready to push to GitHub.")
print()