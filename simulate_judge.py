#!/usr/bin/env python3
"""
simulate_judge.py
Simulates exactly how the magicpin judge tests your bot.

Run:
  python server.py 8080          (terminal 1 - keep running)
  python simulate_judge.py       (terminal 2)
"""

import json, time, urllib.request, urllib.error

BASE = "http://localhost:8080"
PASS = "✅"; FAIL = "❌"; WARN = "⚠️ "
score = {"decision": 0, "specificity": 0, "category_fit": 0,
         "merchant_fit": 0, "engagement": 0}
issues = []

def post(path, body, timeout=60):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode()), e.code

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read())

def push(scope, cid, payload, version=1):
    r, code = post("/v1/context", {
        "scope": scope, "context_id": cid,
        "version": version, "payload": payload,
        "delivered_at": "2026-05-03T10:00:00Z"
    })
    if not r.get("accepted"):
        issues.append(f"CONTEXT REJECTED: scope={scope} id={cid} reason={r.get('reason')}")
    return r

def ok(label, cond, detail=""):
    s = PASS if cond else FAIL
    if not cond:
        issues.append(f"{label}: {detail}")
    print(f"  {s} {label}" + (f"\n     {detail}" if detail else ""))
    return cond

# ──────────────────────────────────────────────────────────────
print("=" * 62)
print("  JUDGE SIMULATION — magicpin Vera AI Challenge")
print("=" * 62)

# PHASE 0 — healthz + metadata
print("\n── PHASE 0: Schema Compliance ──")
h = get("/v1/healthz")
ok("GET /v1/healthz → status=ok", h.get("status") == "ok")
ok("healthz has uptime_seconds", "uptime_seconds" in h)
ok("healthz has contexts_loaded", "contexts_loaded" in h)
m = get("/v1/metadata")
ok("GET /v1/metadata → has team_name", "team_name" in m)
ok("metadata has model", "model" in m)

# ──────────────────────────────────────────────────────────────
# PHASE 1 — Push 17 contexts (5 categories + 5 merchants + 4 customers + 3 triggers)
print("\n── PHASE 1: Context Pushes (17 total) ──")

T = str(int(time.time()))  # unique suffix to avoid suppression

# ── 5 Categories ──
push("category", "dentists", {
    "slug":"dentists",
    "voice":{"tone":"peer_clinical","salutation":"Dr. {first_name}","vocab_no":["guaranteed","miracle"]},
    "offer_catalog":[{"title":"Dental Cleaning @ Rs.299"},{"title":"Teeth Whitening @ Rs.1499"},{"title":"Aligner Consult @ Rs.499"}],
    "peer_stats":{"avg_ctr":0.030,"avg_rating":4.4,"avg_review_count":62,"avg_views_30d":1820},
    "digest":[{"id":"d_jida","source":"JIDA Oct 2026 p.14",
               "title":"3-month fluoride recall cuts caries 38% vs 6-month",
               "trial_n":2100,"patient_segment":"high_risk_adults",
               "summary":"Multi-center Indian trial: 38% lower caries recurrence with 3-month recall in high-risk adults."}],
    "seasonal_beats":[{"month_range":"Oct-Dec","note":"wedding whitening peak"}],
    "trend_signals":[{"query":"clear aligners delhi","delta_yoy":0.62}]
})
push("category", "salons", {
    "slug":"salons",
    "voice":{"tone":"warm_practical","salutation":"{first_name}","vocab_no":["guaranteed results"]},
    "offer_catalog":[{"title":"Bridal Package @ Rs.24999"},{"title":"Keratin Treatment @ Rs.3499"}],
    "peer_stats":{"avg_ctr":0.038,"avg_rating":4.2,"avg_review_count":85,"avg_views_30d":3200},
    "digest":[{"id":"d_diwali","source":"magicpin salon data 2025",
               "title":"Diwali: 3x weekend footfall, advance booking critical",
               "trial_n":None,"patient_segment":None,
               "summary":"Pre-Diwali bridal surge — advance booking critical."}],
    "seasonal_beats":[],"trend_signals":[]
})
push("category", "restaurants", {
    "slug":"restaurants",
    "voice":{"tone":"friendly_operator","salutation":"{first_name}","vocab_no":[]},
    "offer_catalog":[{"title":"BOGO Pizza Tue-Thu"},{"title":"Family Combo @ Rs.699"}],
    "peer_stats":{"avg_ctr":0.036,"avg_rating":4.1,"avg_review_count":120,"avg_views_30d":3800},
    "digest":[{"id":"d_ipl","source":"magicpin data 2025",
               "title":"IPL Saturdays shift -12% restaurant covers",
               "trial_n":None,"patient_segment":None,
               "summary":"Push delivery on IPL Saturdays."}],
    "seasonal_beats":[],"trend_signals":[]
})
push("category", "gyms", {
    "slug":"gyms",
    "voice":{"tone":"energetic_peer","salutation":"{first_name}","vocab_no":["guaranteed weight loss"]},
    "offer_catalog":[{"title":"3-Month Membership @ Rs.4999"},{"title":"Student Batch @ Rs.2499"}],
    "peer_stats":{"avg_ctr":0.032,"avg_rating":4.3,"avg_review_count":48,"avg_views_30d":2200},
    "digest":[{"id":"d_exam","source":"magicpin gym data 2026",
               "title":"Exam season -18% enrollment dip April-May",
               "trial_n":None,"patient_segment":"student_18_24",
               "summary":"Student batch offers offset 60-70% of seasonal dip."}],
    "seasonal_beats":[],"trend_signals":[]
})
push("category", "pharmacies", {
    "slug":"pharmacies",
    "voice":{"tone":"professional_trusted","salutation":"{first_name}","vocab_no":["guaranteed cure"]},
    "offer_catalog":[{"title":"Generic Savings avg Rs.180/prescription"},{"title":"Free BP Check"}],
    "peer_stats":{"avg_ctr":0.028,"avg_rating":4.3,"avg_review_count":42,"avg_views_30d":1600},
    "digest":[{"id":"d_atorva","source":"pharmacy_bulletin_2026",
               "title":"Atorvastatin supply tight — rosuvastatin unaffected",
               "trial_n":None,"patient_segment":"statin_patients",
               "summary":"National atorvastatin constraints 4-6 weeks. Rosuvastatin available."}],
    "seasonal_beats":[],"trend_signals":[]
})
print("  5 categories pushed")

# ── 5 Merchants ──
push("merchant", "m_001_drmeera", {
    "merchant_id":"m_001_drmeera","category_slug":"dentists",
    "identity":{"name":"Dr. Meera Dental Clinic","owner_first_name":"Meera",
                "city":"Delhi","locality":"Lajpat Nagar","languages":["en","hi"],"verified":True},
    "performance":{"views":2410,"calls":18,"ctr":0.021,"leads":9,
                   "delta_7d":{"views_pct":0.18,"calls_pct":-0.05,"ctr_pct":0.02}},
    "offers":[{"title":"Dental Cleaning @ Rs.299","status":"active"}],
    "signals":["ctr_below_peer_median","stale_posts:22d","high_risk_adult_cohort"],
    "subscription":{"status":"active","plan":"Pro","days_remaining":82},
    "customer_aggregate":{"total_unique_ytd":540,"lapsed_180d_plus":78,
                          "retention_6mo_pct":0.38,"high_risk_adult_count":124},
    "review_themes":[{"theme":"wait_time","sentiment":"neg","occurrences_30d":3,
                      "common_quote":"had to wait 30 min on Sunday"}],
    "conversation_history":[]
})
push("merchant", "m_002_bharat", {
    "merchant_id":"m_002_bharat","category_slug":"dentists",
    "identity":{"name":"Bharat Dental Care","owner_first_name":"Bharat",
                "city":"Mumbai","locality":"Andheri West","languages":["en","hi"],"verified":False},
    "performance":{"views":980,"calls":4,"ctr":0.018,"leads":2,
                   "delta_7d":{"views_pct":-0.22,"calls_pct":-0.5,"ctr_pct":-0.1}},
    "offers":[],"signals":["renewal_due_soon:12d","perf_dip_severe","unverified_gbp","no_active_offers"],
    "subscription":{"status":"active","plan":"Pro","days_remaining":12},
    "customer_aggregate":{"total_unique_ytd":220,"lapsed_180d_plus":95,"retention_6mo_pct":0.18},
    "review_themes":[],"conversation_history":[]
})
push("merchant", "m_003_studio11", {
    "merchant_id":"m_003_studio11","category_slug":"salons",
    "identity":{"name":"Studio11 Family Salon","owner_first_name":"Lakshmi",
                "city":"Hyderabad","locality":"Kapra","languages":["en","hi","te"],"verified":True},
    "performance":{"views":5430,"calls":61,"ctr":0.041,"leads":38,
                   "delta_7d":{"views_pct":0.12,"calls_pct":0.2,"ctr_pct":0.03}},
    "offers":[{"title":"Bridal Package @ Rs.24999","status":"active"},
              {"title":"Keratin Treatment @ Rs.3499","status":"active"}],
    "signals":["bridal_peak_incoming","high_retention"],
    "subscription":{"status":"active","plan":"Pro","days_remaining":142},
    "customer_aggregate":{"total_unique_ytd":1240,"lapsed_180d_plus":180,"retention_6mo_pct":0.62},
    "review_themes":[{"theme":"bridal_quality","sentiment":"pos","occurrences_30d":8,
                      "common_quote":"best bridal makeup in Kapra area"}],
    "conversation_history":[]
})
push("merchant", "m_004_pizza", {
    "merchant_id":"m_004_pizza","category_slug":"restaurants",
    "identity":{"name":"SK Pizza Junction","owner_first_name":"Suresh",
                "city":"Delhi","locality":"Sant Nagar","languages":["en","hi"],"verified":True},
    "performance":{"views":3100,"calls":22,"ctr":0.033,"leads":18,
                   "delta_7d":{"views_pct":0.05,"calls_pct":-0.1,"ctr_pct":0.01}},
    "offers":[{"title":"BOGO Pizza Tue-Thu","status":"active"}],
    "signals":["trial_expiring_soon","delivery_preference"],
    "subscription":{"status":"trial","plan":"Trial","days_remaining":8},
    "customer_aggregate":{"total_unique_ytd":920,"lapsed_180d_plus":310,"retention_6mo_pct":0.44},
    "review_themes":[{"theme":"delivery_time","sentiment":"neg","occurrences_30d":5,
                      "common_quote":"delivery took 45 min"}],
    "conversation_history":[]
})
push("merchant", "m_005_powerhouse", {
    "merchant_id":"m_005_powerhouse","category_slug":"gyms",
    "identity":{"name":"PowerHouse Fitness","owner_first_name":"Kiran",
                "city":"Bangalore","locality":"Indiranagar","languages":["en","hi"],"verified":True},
    "performance":{"views":2800,"calls":19,"ctr":0.029,"leads":14,
                   "delta_7d":{"views_pct":-0.18,"calls_pct":-0.25,"ctr_pct":-0.08}},
    "offers":[{"title":"3-Month Membership @ Rs.4999","status":"active"},
              {"title":"Personal Training Trial @ Rs.999","status":"active"}],
    "signals":["seasonal_dip_expected","perf_dip_moderate"],
    "subscription":{"status":"active","plan":"Pro","days_remaining":88},
    "customer_aggregate":{"total_unique_ytd":480,"lapsed_180d_plus":165,"retention_6mo_pct":0.42},
    "review_themes":[],"conversation_history":[]
})
print("  5 merchants pushed")

# ── 4 Customers ──
push("customer", "c_001_priya", {
    "customer_id":"c_001_priya","merchant_id":"m_001_drmeera",
    "identity":{"name":"Priya","language_pref":"hi-en mix","age_band":"25-35"},
    "relationship":{"first_visit":"2025-11-04","last_visit":"2026-05-12",
                    "visits_total":4,"services_received":["cleaning","whitening","cleaning"]},
    "state":"lapsed_soft",
    "preferences":{"preferred_slots":"weekday_evening","channel":"whatsapp","reminder_opt_in":True},
    "consent":{"scope":["recall_reminders","appointment_reminders"]}
})
push("customer", "c_002_kavya", {
    "customer_id":"c_002_kavya","merchant_id":"m_003_studio11",
    "identity":{"name":"Kavya","language_pref":"english","age_band":"25-35"},
    "relationship":{"first_visit":"2026-03-22","last_visit":"2026-03-22",
                    "visits_total":1,"services_received":["bridal_trial"]},
    "state":"new",
    "preferences":{"preferred_slots":"saturday","channel":"whatsapp","reminder_opt_in":True},
    "consent":{"scope":["bridal_package_followup","appointment_reminders"]},
    "wedding_details":{"date":"2026-11-08","stage":"trial_done"}
})
push("customer", "c_003_rashmi", {
    "customer_id":"c_003_rashmi","merchant_id":"m_005_powerhouse",
    "identity":{"name":"Rashmi","language_pref":"english","age_band":"30-40"},
    "relationship":{"first_visit":"2025-09-10","last_visit":"2026-02-28",
                    "visits_total":22,"services_received":["membership_x4","PT_intro"],
                    "lifetime_value":4490},
    "state":"lapsed_hard",
    "preferences":{"preferred_slots":"weekday_evening","channel":"whatsapp","reminder_opt_in":True},
    "consent":{"scope":["renewal_reminders","winback_offers"]}
})
push("customer", "c_004_amit", {
    "customer_id":"c_004_amit","merchant_id":"m_004_pizza",
    "identity":{"name":"Amit","language_pref":"hi-en mix","age_band":"25-35"},
    "relationship":{"first_visit":"2026-04-12","last_visit":"2026-04-22",
                    "visits_total":5,"services_received":["delivery","dine_in","delivery"],
                    "favourite_dish":"BBQ Chicken Pizza"},
    "state":"active",
    "preferences":{"preferred_slots":"fri_sat_night","channel":"whatsapp","reminder_opt_in":True},
    "consent":{"scope":["promotional_offers","match_night_specials"]}
})
print("  4 customers pushed")

# ── 3 Triggers ──
TRIGGERS = [
    ("trg_recall_"+T, "customer", "recall_due", "m_001_drmeera", "c_001_priya",
     {"service_due":"6_month_cleaning","last_service_date":"2026-05-12",
      "available_slots":[{"iso":"2026-11-05T18:00:00+05:30","label":"Wed 5 Nov, 6pm"},
                         {"iso":"2026-11-06T17:00:00+05:30","label":"Thu 6 Nov, 5pm"}]}),
    ("trg_regulation_"+T, "merchant", "regulation_change", "m_001_drmeera", None,
     {"category":"dentists","top_item_id":"d_jida","deadline_iso":"2026-12-15"}),
    ("trg_ipl_"+T, "merchant", "ipl_match_today", "m_004_pizza", None,
     {"match":"DC vs MI","venue":"Arun Jaitley Stadium","city":"Delhi",
      "match_time_iso":"2026-05-03T19:30:00+05:30","is_weeknight":False}),
]
trigger_ids = []
for tid, scope, kind, mid, cid, payload in TRIGGERS:
    push("trigger", tid, {
        "id":tid,"scope":scope,"kind":kind,"source":"external",
        "merchant_id":mid,"customer_id":cid,
        "payload":payload,"urgency":3,
        "suppression_key":f"{kind}:{mid}:{T}",
        "expires_at":"2026-12-01T00:00:00Z"
    })
    trigger_ids.append(tid)
print("  3 triggers pushed")
print(f"  Total: 17 context pushes ✅")

# ──────────────────────────────────────────────────────────────
# PHASE 2 — Tick with all 3 triggers
print("\n── PHASE 2: /v1/tick with 3 triggers ──")

tick_r, _ = post("/v1/tick", {
    "now": "2026-05-03T10:30:00Z",
    "available_triggers": trigger_ids
})
actions = tick_r.get("actions", [])
ok("tick returns actions[]", isinstance(actions, list))
ok("all 3 triggers fire", len(actions) == 3, f"Got {len(actions)} actions (expected 3)")

conv_ids = {}
for action in actions:
    tid = action.get("trigger_id","")
    kind = action.get("trigger_id","").split("_")[1] if "_" in tid else "unknown"
    body = action.get("body","")
    cid = action.get("conversation_id","")
    mid = action.get("merchant_id","")
    ok(f"  Action has body (trigger: {tid[:25]}...)", bool(body.strip()), f"body={body[:60]}")
    ok(f"  Action has suppression_key", bool(action.get("suppression_key","")))
    ok(f"  Action has send_as", action.get("send_as") in ("vera","merchant_on_behalf"))
    conv_ids[tid] = cid
    print(f"     💬 {body[:80]}...")

# ──────────────────────────────────────────────────────────────
# PHASE 3 — Reply Tests
print("\n── PHASE 3: Replay Tests ──")

if actions:
    # Use first action (regulation_change for Dr. Meera)
    reg_action = next((a for a in actions if "regulation" in a.get("trigger_id","")), actions[0])
    reg_conv = reg_action.get("conversation_id","")
    reg_mid = reg_action.get("merchant_id","")

    print("\n  3a. Merchant contextual reply")
    r1, _ = post("/v1/reply", {
        "conversation_id": reg_conv,
        "merchant_id": reg_mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Got it doc — need help auditing my X-ray setup. We have an old D-speed film unit.",
        "received_at": "2026-05-03T10:35:00Z",
        "turn_number": 2
    })
    ok("  Merchant reply → action=send", r1.get("action") == "send", f"action={r1.get('action')}")
    ok("  Reply not generic Namaste", "Namaste! Aapka message mila" not in r1.get("body",""),
       f"body={r1.get('body','')[:80]}")
    print(f"     💬 {r1.get('body','')[:80]}...")

    print("\n  3b. Customer slot pick")
    recall_action = next((a for a in actions if "recall" in a.get("trigger_id","")), None)
    if recall_action:
        r2, _ = post("/v1/reply", {
            "conversation_id": recall_action.get("conversation_id",""),
            "merchant_id": recall_action.get("merchant_id",""),
            "customer_id": "c_001_priya",
            "from_role": "customer",
            "message": "Yes please book me for Wed 5 Nov, 6pm.",
            "received_at": "2026-05-03T10:36:00Z",
            "turn_number": 2
        })
        ok("  Customer reply → action=send", r2.get("action") == "send")
        body2 = r2.get("body","")
        ok("  Customer reply addresses Priya", "Priya" in body2 or len(body2) > 30,
           f"body={body2[:80]}")
        ok("  Not generic Namaste", "Namaste! Aapka message mila" not in body2)
        print(f"     💬 {body2[:80]}...")

    print("\n  3c. Auto-reply hell test (4 identical messages)")
    ipl_action = next((a for a in actions if "ipl" in a.get("trigger_id","")), actions[-1])
    ipl_conv = ipl_action.get("conversation_id","")
    ipl_mid = ipl_action.get("merchant_id","")
    AUTO_MSG = "Thank you for contacting us. This is an automated response from our system."
    results_auto = []
    for i in range(4):
        ra, _ = post("/v1/reply", {
            "conversation_id": ipl_conv,
            "merchant_id": ipl_mid,
            "customer_id": None,
            "from_role": "merchant",
            "message": AUTO_MSG,
            "received_at": f"2026-05-03T10:3{i+7}:00Z",
            "turn_number": i+2
        })
        results_auto.append(ra.get("action",""))
        print(f"     Turn {i+1}: action={ra.get('action')}")
    ok("  Auto-reply eventually returns end", "end" in results_auto,
       f"actions={results_auto}")
    ok("  No endless send→send→send", results_auto.count("send") <= 2,
       f"Got {results_auto.count('send')} sends in a row")

    print("\n  3d. STOP handling")
    r_stop, _ = post("/v1/reply", {
        "conversation_id": reg_conv,
        "merchant_id": reg_mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "STOP",
        "received_at": "2026-05-03T10:40:00Z",
        "turn_number": 5
    })
    ok("  STOP → action=end", r_stop.get("action") == "end",
       f"action={r_stop.get('action')}, body={r_stop.get('body','')[:40]}")

# ──────────────────────────────────────────────────────────────
# PHASE 4 — Score messages (simple heuristic)
print("\n── PHASE 4: Message Quality Check ──")
for action in actions:
    body = action.get("body","")
    merchant_id = action.get("merchant_id","")

    has_number = any(c.isdigit() for c in body)
    is_customer_facing = action.get("send_as") == "merchant_on_behalf"
    has_merchant_name = (
        any(n in body for n in ["Priya","Kavya","Rashmi","Amit"])
        if is_customer_facing else
        any(n in body for n in ["Meera","Suresh","Lakshmi","Kiran","Bharat","Dr."])
    )
    has_cta = any(w in body.lower() for w in
                  ["reply yes","reply stop","?","shall we","would you","want to","kya aap"])
    not_generic = not any(w in body.lower() for w in
                          ["increase your sales","great opportunity","amazing offer"])
    short_enough = len(body) <= 500

    print(f"\n  Trigger: {action.get('trigger_id','')[:35]}")
    print(f"  Body: {body[:100]}...")
    ok("    Has specific number/stat", has_number, body[:60])
    ok("    Addresses merchant by name", has_merchant_name, body[:60])
    ok("    Has a CTA", has_cta, body[:60])
    ok("    Not generic", not_generic, body[:60])
    ok("    Appropriate length (<500 chars)", short_enough, f"{len(body)} chars")

# ──────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
print("  SIMULATION COMPLETE")
print("=" * 62)
if issues:
    print(f"\n⚠️  Issues found ({len(issues)}):")
    for issue in issues:
        print(f"  {FAIL} {issue}")
else:
    print("\n✅ No issues found — bot ready for judge!")
print()