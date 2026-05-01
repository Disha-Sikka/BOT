"""
Vera Bot — magicpin AI Challenge Submission
==========================================
Uses Mistral AI API (FREE tier — no credit card needed).
Model: mistral-small-latest

3-layer architecture:
  Layer 1: Decision Engine  — pure logic, no LLM
  Layer 2: Context Builder  — assembles grounded fact block
  Layer 3: Groq LLM         — writes message, constrained to fact block
"""

import json
import os
import urllib.request
import urllib.error
from typing import Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env file automatically (put MISTRAL_API_KEY=your-key in a .env file
# in the same folder as bot.py — no need to set env variables manually)
# Add: GEMINI_API_KEY=AIza...
# Get free key: https://aistudio.google.com/app/apikey (no credit card)
# ---------------------------------------------------------------------------
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _val.strip())

CATEGORY_VOICE = {
    "dentists":    {"tone":"peer_clinical","salutation":"Dr. {first_name}","vocab_no":["guaranteed","100% safe","completely cure","miracle","best in city"]},
    "salons":      {"tone":"warm_practical","salutation":"{first_name}","vocab_no":["guaranteed results","100% satisfaction"]},
    "restaurants": {"tone":"friendly_operator","salutation":"{first_name}","vocab_no":[]},
    "gyms":        {"tone":"energetic_peer","salutation":"{first_name}","vocab_no":["guaranteed weight loss"]},
    "pharmacies":  {"tone":"professional_trusted","salutation":"{first_name}","vocab_no":["guaranteed cure","miracle drug"]},
}

TRIGGER_CTA = {
    "research_digest":"open_ended","cde_opportunity":"open_ended","curious_ask_due":"open_ended",
    "milestone_reached":"open_ended","review_theme_emerged":"open_ended","active_planning_intent":"open_ended",
    "recall_due":"binary_yes_stop","renewal_due":"binary_yes_stop","winback_eligible":"binary_yes_stop",
    "customer_lapsed_hard":"binary_yes_stop","supply_alert":"binary_yes_stop","festival_upcoming":"binary_yes_stop",
    "wedding_package_followup":"binary_yes_stop","trial_followup":"binary_yes_stop","chronic_refill_due":"binary_yes_stop",
    "perf_dip":"binary_yes_stop","perf_spike":"binary_yes_stop","competitor_opened":"binary_yes_stop",
    "gbp_unverified":"binary_yes_stop","dormant_with_vera":"binary_yes_stop","ipl_match_today":"binary_yes_stop",
    "regulation_change":"binary_yes_stop","seasonal_perf_dip":"binary_yes_stop","category_seasonal":"binary_yes_stop",
}

TRIGGER_LEVERS = {
    "research_digest":["specificity","curiosity","reciprocity"],
    "regulation_change":["specificity","loss_aversion","reciprocity"],
    "recall_due":["specificity","loss_aversion","single_binary"],
    "perf_dip":["specificity","loss_aversion","social_proof"],
    "perf_spike":["specificity","curiosity","single_binary"],
    "renewal_due":["loss_aversion","specificity","social_proof"],
    "festival_upcoming":["specificity","loss_aversion","effort_externalization"],
    "ipl_match_today":["specificity","loss_aversion","effort_externalization"],
    "competitor_opened":["specificity","loss_aversion","social_proof"],
    "milestone_reached":["specificity","curiosity","reciprocity"],
    "curious_ask_due":["asking_merchant","reciprocity","effort_externalization"],
    "winback_eligible":["specificity","loss_aversion","social_proof"],
    "customer_lapsed_hard":["specificity","loss_aversion","single_binary"],
    "review_theme_emerged":["specificity","loss_aversion","effort_externalization"],
    "supply_alert":["specificity","loss_aversion","single_binary"],
    "gbp_unverified":["specificity","loss_aversion","effort_externalization"],
    "dormant_with_vera":["curiosity","social_proof","single_binary"],
    "cde_opportunity":["specificity","curiosity","reciprocity"],
    "seasonal_perf_dip":["specificity","loss_aversion","social_proof"],
    "category_seasonal":["specificity","loss_aversion","effort_externalization"],
    "wedding_package_followup":["specificity","loss_aversion","single_binary"],
    "trial_followup":["specificity","curiosity","single_binary"],
    "chronic_refill_due":["specificity","loss_aversion","single_binary"],
    "active_planning_intent":["specificity","effort_externalization","single_binary"],
}


def decide(trigger, merchant, category, customer):
    kind = trigger.get("kind", "scheduled_recurring")
    scope = trigger.get("scope", "merchant")
    is_customer_facing = scope == "customer" and customer is not None
    cta = TRIGGER_CTA.get(kind, "open_ended")
    send_as = "merchant_on_behalf" if is_customer_facing else "vera"
    levers = TRIGGER_LEVERS.get(kind, ["specificity", "curiosity"])

    top_item_id = trigger.get("payload", {}).get("top_item_id")
    digest = list(category.get("digest", []))
    if top_item_id:
        idx = next((i for i, d in enumerate(digest) if d.get("id") == top_item_id), -1)
        if idx > 0:
            digest.insert(0, digest.pop(idx))

    peer_ctr = category.get("peer_stats", {}).get("avg_ctr", 0)
    merchant_ctr = merchant.get("performance", {}).get("ctr", 0)
    ctr_gap = round((peer_ctr - merchant_ctr) * 100, 2) if peer_ctr > merchant_ctr else None
    signals = merchant.get("signals", [])

    return {
        "kind": kind, "cta": cta, "send_as": send_as, "levers": levers,
        "digest": digest[:2], "ctr_gap": ctr_gap,
        "peer_ctr": peer_ctr, "merchant_ctr": merchant_ctr,
        "is_customer_facing": is_customer_facing,
        "has_no_offers": "no_active_offers" in signals,
    }


def build_context_block(category, merchant, trigger, customer, decision):
    cat_slug = category.get("slug", "")
    voice = CATEGORY_VOICE.get(cat_slug, {})
    peer = category.get("peer_stats", {})
    m_id = merchant.get("identity", {})
    m_perf = merchant.get("performance", {})
    m_sub = merchant.get("subscription", {})
    m_agg = merchant.get("customer_aggregate", {})
    first_name = m_id.get("owner_first_name", m_id.get("name", ""))
    salutation = voice.get("salutation", "{first_name}").replace("{first_name}", first_name)

    lines = ["=== CATEGORY ==="]
    lines.append(f"Slug: {cat_slug} | Tone: {voice.get('tone','')} | Salutation: {salutation}")
    lines.append(f"Peer: avg_ctr={peer.get('avg_ctr')}, avg_rating={peer.get('avg_rating')}, avg_reviews={peer.get('avg_review_count')}")
    lines.append(f"Catalog offers: {'; '.join(o['title'] for o in category.get('offer_catalog',[])[:5])}")
    if decision["digest"]:
        lines.append("Digest (USE THESE ONLY — do NOT fabricate):")
        for d in decision["digest"]:
            lines.append(f"  [{d.get('source','')}] {d.get('title','')} n={d.get('trial_n','')} seg={d.get('patient_segment','')}")
            if d.get("summary"):
                lines.append(f"    {d['summary'][:200]}")
    if category.get("seasonal_beats"):
        lines.append(f"Seasonal: {json.dumps(category['seasonal_beats'][:2])}")
    if category.get("trend_signals"):
        lines.append(f"Trends: {json.dumps(category['trend_signals'][:2])}")

    lines.append("\n=== MERCHANT ===")
    lines.append(f"Name: {m_id.get('name','')} | Salutation: {salutation}")
    lines.append(f"City: {m_id.get('city','')}, {m_id.get('locality','')} | Languages: {m_id.get('languages',[])} | GBP verified: {m_id.get('verified',False)}")
    lines.append(f"Subscription: {m_sub.get('status')} plan={m_sub.get('plan')} days={m_sub.get('days_remaining')}")
    lines.append(f"Perf (30d): views={m_perf.get('views')} calls={m_perf.get('calls')} ctr={m_perf.get('ctr')} leads={m_perf.get('leads')}")
    delta = m_perf.get("delta_7d", {})
    if delta:
        lines.append(f"7d delta: views={delta.get('views_pct')} calls={delta.get('calls_pct')} ctr={delta.get('ctr_pct')}")
    if decision["ctr_gap"]:
        lines.append(f"CTR GAP: merchant={decision['merchant_ctr']} vs peer={decision['peer_ctr']} (gap={decision['ctr_gap']}pp BELOW peer)")
    active = [o["title"] for o in merchant.get("offers",[]) if o.get("status")=="active"]
    expired = [o["title"] for o in merchant.get("offers",[]) if o.get("status")=="expired"]
    lines.append(f"Active offers: {active or 'NONE'}")
    if expired:
        lines.append(f"Expired offers: {expired}")
    if decision["has_no_offers"]:
        lines.append("SIGNAL: No active offers — weakness to address.")
    lines.append(f"Signals: {merchant.get('signals',[])}")
    lines.append(f"Customer agg: total_ytd={m_agg.get('total_unique_ytd')} lapsed_180d={m_agg.get('lapsed_180d_plus')} retention_6mo={m_agg.get('retention_6mo_pct')}")
    for k, v in m_agg.items():
        if k not in ("total_unique_ytd","lapsed_180d_plus","retention_6mo_pct"):
            lines.append(f"  agg.{k}: {v}")
    for rt in merchant.get("review_themes",[])[:3]:
        lines.append(f'  Review: {rt["theme"]} ({rt["sentiment"]}, {rt["occurrences_30d"]}x): "{rt.get("common_quote","")}"')
    for h in merchant.get("conversation_history",[])[-3:]:
        lines.append(f"  [{h.get('from')}] {h.get('body','')[:120]} [{h.get('engagement','')}]")

    lines.append("\n=== TRIGGER ===")
    lines.append(f"Kind: {trigger.get('kind')} | Urgency: {trigger.get('urgency',2)}/5")
    if trigger.get("payload"):
        lines.append(f"Payload: {json.dumps(trigger['payload'])}")

    if customer:
        c_id = customer.get("identity", {})
        c_rel = customer.get("relationship", {})
        lines.append("\n=== CUSTOMER ===")
        lines.append(f"Name: {c_id.get('name')} | Lang: {c_id.get('language_pref')} | State: {customer.get('state')}")
        lines.append(f"Last visit: {c_rel.get('last_visit')} | Visits: {c_rel.get('visits_total')} | Services: {c_rel.get('services_received',[])}")
        lines.append(f"Preferred slots: {customer.get('preferences',{}).get('preferred_slots')}")
        if customer.get("wedding_details"):
            lines.append(f"Wedding: {json.dumps(customer['wedding_details'])}")

    lines.append("\n=== DECISION (FOLLOW EXACTLY) ===")
    lines.append(f"send_as: {decision['send_as']} | cta: {decision['cta']} | levers: {decision['levers']}")

    return "\n".join(lines)


def call_llm(system: str, user: str) -> str:
    """
    Calls Mistral AI API — FREE tier, no credit card needed.
    Model: mistral-small-latest

    Get your free key (2 minutes):
      1. Go to https://console.mistral.ai
      2. Sign up with Google or email (no credit card)
      3. Go to API Keys section -> Create new key
      4. Copy the key (starts with ...)
      5. Add to .env:  MISTRAL_API_KEY=your-key-here
    """
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "MISTRAL_API_KEY not set.\n"
            "Get a free key at: https://console.mistral.ai (no credit card)\n"
            "Add this to your .env: MISTRAL_API_KEY=your-key-here"
        )

    payload = {
        "model": "mistral-small-latest",
        "temperature": 0,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"Mistral API error {e.code}: {error_body}")


def compose(category: dict, merchant: dict, trigger: dict, customer=None) -> dict:
    decision      = decide(trigger, merchant, category, customer)
    context_block = build_context_block(category, merchant, trigger, customer, decision)

    cat_slug = category.get("slug", "")
    voice    = CATEGORY_VOICE.get(cat_slug, {})

    if decision["cta"] == "binary_yes_stop":
        cta_instr = "End with: Reply YES / STOP"
    else:
        cta_instr = "End with an open question or low-friction offer (no YES/STOP)."

    system = (
        "You are Vera, magicpin's merchant AI assistant. Write specific, grounded WhatsApp messages.\n\n"
        "RULES (violating any = fail):\n"
        "1. Use ONLY facts from context. NEVER invent numbers, names, citations, or offers.\n"
        "2. One CTA maximum — place it in the LAST sentence.\n"
        "3. Hook immediately — no preambles like 'I hope you are well'.\n"
        "4. No generic phrases: 'increase your sales', 'great opportunity', 'amazing offer'.\n"
        "5. Anchor on at least ONE verifiable number or source from context.\n"
        "6. Match the merchant's language preference (hi-en mix if specified).\n"
        "7. 3-6 sentences — WhatsApp length.\n"
        "8. Output ONLY the message body. No JSON, no labels, no explanation.\n"
        + (
            "\nCUSTOMER-FACING: No medical claims. Message is FROM the merchant's WhatsApp. "
            "Use customer's name. Match their language pref.\n"
            if decision["is_customer_facing"] else
            f"\nMerchant-facing for {cat_slug}. Tone: {voice.get('tone','')}. "
            f"FORBIDDEN: {', '.join(voice.get('vocab_no',[]))}. "
            f"{'Binary CTA: Reply YES / STOP.' if decision['cta']=='binary_yes_stop' else 'Open CTA: question or low-friction offer.'}\n"
        )
    )

    user = (
        f"Here is the full context:\n\n{context_block}\n\n"
        f"Compose the WhatsApp message.\n"
        f"- {cta_instr}\n"
        f"- Use levers: {decision['levers']}\n"
        f"- Anchor on at least one specific number or source\n"
        f"- DO NOT fabricate\n"
        f"- Output ONLY the message body."
    )

    body = call_llm(system, user)

    m_name = merchant.get("identity", {}).get("name", "")
    kind   = trigger.get("kind", "")
    return {
        "body":            body,
        "cta":             decision["cta"],
        "send_as":         decision["send_as"],
        "suppression_key": trigger.get("suppression_key", f"{kind}:{merchant.get('merchant_id','')}"),
        "rationale":       (f"Trigger: {kind} for {m_name} ({cat_slug}). "
                            f"Levers: {', '.join(decision['levers'])}. "
                            f"send_as={decision['send_as']}, cta={decision['cta']}."),
    }