"""
server.py — HTTP API for magicpin AI Challenge
Exposes: POST /v1/context, POST /v1/tick, POST /v1/reply,
         GET /v1/healthz, GET /v1/metadata
"""

import json
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from flask import Flask, request, jsonify

import bot

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vera-bot")

app = Flask(__name__)
START_TIME = time.time()


@app.route("/", methods=["GET"])
def root():
    return """<!DOCTYPE html>
<html>
<head>
    <title>Vera Bot — magicpin AI Challenge</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 700px; margin: 60px auto; padding: 0 20px; background: #f9f9f9; }
        h1 { color: #1a1a1a; font-size: 28px; }
        .badge { background: #22c55e; color: white; padding: 4px 12px; border-radius: 20px; font-size: 13px; margin-left: 10px; }
        p { color: #555; line-height: 1.6; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 32px; }
        .card { background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 20px; text-decoration: none; color: inherit; display: block; }
        .card:hover { border-color: #6366f1; box-shadow: 0 2px 8px rgba(99,102,241,0.1); }
        .card h3 { margin: 0 0 6px; font-size: 15px; color: #1a1a1a; }
        .card .method { font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; margin-right: 6px; }
        .get { background: #dcfce7; color: #16a34a; }
        .post { background: #dbeafe; color: #1d4ed8; }
        .card p { font-size: 13px; color: #6b7280; margin: 6px 0 0; }
        .info { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin-top: 24px; font-size: 14px; }
        .info strong { color: #15803d; }
    </style>
</head>
<body>
    <h1>Vera Bot <span class="badge">● Live</span></h1>
    <p>magicpin AI Challenge submission — AI assistant that composes grounded WhatsApp messages for merchants using a 3-layer decision engine + Mistral AI.</p>

    <div class="grid">
        <a class="card" href="/v1/healthz">
            <h3><span class="method get">GET</span> /v1/healthz</h3>
            <p>Liveness check — returns status and context counts</p>
        </a>
        <a class="card" href="/v1/metadata">
            <h3><span class="method get">GET</span> /v1/metadata</h3>
            <p>Team info, model, approach description</p>
        </a>
        <div class="card">
            <h3><span class="method post">POST</span> /v1/context</h3>
            <p>Push category / merchant / customer / trigger context</p>
        </div>
        <div class="card">
            <h3><span class="method post">POST</span> /v1/tick</h3>
            <p>Wake-up call — bot decides what messages to send</p>
        </div>
        <div class="card">
            <h3><span class="method post">POST</span> /v1/reply</h3>
            <p>Handle merchant reply — send / wait / end</p>
        </div>
        <a class="card" href="/v1/test" style="border-color:#6366f1;background:#faf5ff;">
            <h3><span class="method get" style="background:#ede9fe;color:#7c3aed;">GET</span> /v1/test</h3>
            <p>🧪 See a live generated message in your browser</p>
        </a>
    </div>

    <div class="info">
        <strong>Architecture:</strong> Decision Engine (pure Python) → Context Builder → Mistral AI (temp=0)<br>
        <strong>Model:</strong> mistral-small-latest &nbsp;|&nbsp; <strong>Team:</strong> Disha Sikka
    </div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# IN-MEMORY STATE
# ---------------------------------------------------------------------------
contexts = {
    "category": {},   # slug → {version, payload}
    "merchant": {},   # merchant_id → {version, payload}
    "customer": {},   # customer_id → {version, payload}
    "trigger": {},    # trigger_id → {version, payload}
}

conversations = {}  # conversation_id → {merchant_id, customer_id, history, suppressed_keys}
suppressed = set()  # suppression_keys already sent

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def get_context(scope: str, context_id: str) -> Optional[dict]:
    entry = contexts.get(scope, {}).get(context_id)
    return entry["payload"] if entry else None


def find_merchant_category(merchant: dict) -> Optional[dict]:
    slug = merchant.get("category_slug")
    if slug:
        return get_context("category", slug)
    return None


def resolve_trigger(trigger_id: str):
    """Returns (trigger, merchant, category, customer) or None tuple."""
    trg = get_context("trigger", trigger_id)
    if not trg:
        return None, None, None, None
    merchant_id = trg.get("merchant_id") or trg.get("payload", {}).get("merchant_id")
    merchant = get_context("merchant", merchant_id) if merchant_id else None
    category = find_merchant_category(merchant) if merchant else None
    customer_id = trg.get("customer_id")
    customer = get_context("customer", customer_id) if customer_id else None
    return trg, merchant, category, customer


# ---------------------------------------------------------------------------
# GET /v1/test — browser-friendly demo page
# ---------------------------------------------------------------------------

@app.route("/v1/test", methods=["GET"])
def test_compose():
    """Generates a real message live and shows it in the browser."""
    import os, json
    from pathlib import Path

    # Load seed data from dataset folder
    base = Path(__file__).parent
    dataset = base / "dataset"

    try:
        merchants = json.load(open(dataset / "merchants_seed.json"))["merchants"]
        triggers  = json.load(open(dataset / "triggers_seed.json"))["triggers"]
        dentists  = json.load(open(dataset / "categories" / "dentists.json"))

        # Pick merchant + trigger (can change index for different examples)
        merchant = merchants[0]
        trigger  = triggers[0]

        result = bot.compose(dentists, merchant, trigger, customer=None)
        body    = result["body"]
        cta     = result["cta"]
        send_as = result["send_as"]
        rationale = result["rationale"]
        status  = "success"
        error   = ""
    except Exception as e:
        body = rationale = ""
        cta = send_as = ""
        status = "error"
        error = str(e)

    color = "#22c55e" if status == "success" else "#ef4444"
    label = "✅ Message Generated" if status == "success" else "❌ Error"

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Vera Bot — Live Test</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 750px; margin: 60px auto; padding: 0 20px; background: #f9f9f9; }}
        h1 {{ color: #1a1a1a; }}
        a.back {{ color: #6366f1; font-size: 14px; text-decoration: none; }}
        .status {{ display: inline-block; background: {color}; color: white; padding: 4px 14px; border-radius: 20px; font-size: 13px; margin-bottom: 24px; }}
        .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 24px; margin-bottom: 16px; }}
        .card h3 {{ margin: 0 0 12px; font-size: 14px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; }}
        .message {{ font-size: 16px; line-height: 1.7; color: #1a1a1a; white-space: pre-wrap; }}
        .pill {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-right: 8px; }}
        .vera {{ background: #dbeafe; color: #1d4ed8; }}
        .open {{ background: #fef9c3; color: #854d0e; }}
        .binary {{ background: #fee2e2; color: #991b1b; }}
        .rationale {{ font-size: 13px; color: #6b7280; line-height: 1.6; }}
        .context {{ font-size: 12px; color: #9ca3af; }}
        .btn {{ display: inline-block; margin-top: 20px; background: #6366f1; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-size: 14px; }}
        .btn:hover {{ background: #4f46e5; }}
        .error {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px; color: #991b1b; font-size: 14px; }}
    </style>
</head>
<body>
    <a class="back" href="/">← Back to home</a>
    <h1>Live Message Test</h1>
    <div class="status">{label}</div>

    {"f" if status == "error" else ""}

    {"<div class=\"error\"><strong>Error:</strong> " + error + "</div>" if status == "error" else f"""
    <div class="card">
        <h3>Generated WhatsApp Message</h3>
        <div class="message">{body}</div>
    </div>

    <div class="card">
        <h3>Message Properties</h3>
        <span class="pill vera">{send_as}</span>
        <span class="pill {'binary' if cta == 'binary_yes_stop' else 'open'}">{cta}</span>
    </div>

    <div class="card">
        <h3>Rationale</h3>
        <div class="rationale">{rationale}</div>
    </div>

    <div class="context">
        Merchant: Dr. Meera's Dental Clinic, Delhi &nbsp;|&nbsp;
        Trigger: research_digest (JIDA Oct 2026) &nbsp;|&nbsp;
        Model: mistral-small-latest
    </div>
    """}

    <a class="btn" href="/v1/test">🔄 Generate Again</a>
</body>
</html>"""


# ---------------------------------------------------------------------------
# POST /v1/context
# ---------------------------------------------------------------------------

@app.route("/v1/context", methods=["POST"])
def receive_context():
    data = request.get_json(force=True)
    scope = data.get("scope")
    context_id = data.get("context_id")
    version = data.get("version", 1)
    payload = data.get("payload", {})

    valid_scopes = ("category", "merchant", "customer", "trigger")
    if scope not in valid_scopes:
        return jsonify({"accepted": False, "reason": "invalid_scope",
                        "details": f"scope must be one of {valid_scopes}"}), 400

    if context_id is None:
        return jsonify({"accepted": False, "reason": "missing_context_id"}), 400

    existing = contexts[scope].get(context_id)
    if existing and existing["version"] > version:
        return jsonify({"accepted": False, "reason": "stale_version",
                        "current_version": existing["version"]}), 409

    contexts[scope][context_id] = {"version": version, "payload": payload}
    ack_id = f"ack_{uuid.uuid4().hex[:8]}"
    stored_at = datetime.now(timezone.utc).isoformat()
    logger.info(f"Context stored: scope={scope} id={context_id} v={version}")

    return jsonify({"accepted": True, "ack_id": ack_id, "stored_at": stored_at})


# ---------------------------------------------------------------------------
# POST /v1/tick
# ---------------------------------------------------------------------------

@app.route("/v1/tick", methods=["POST"])
def tick():
    data = request.get_json(force=True)
    now_str = data.get("now", datetime.now(timezone.utc).isoformat())
    available_triggers = data.get("available_triggers", [])

    actions = []

    for trigger_id in available_triggers:
        trg, merchant, category, customer = resolve_trigger(trigger_id)
        if not trg or not merchant or not category:
            continue

        sup_key = trg.get("suppression_key", trigger_id)
        if sup_key in suppressed:
            logger.info(f"Suppressed trigger {trigger_id} (key={sup_key})")
            continue

        # Check expiry
        expires = trg.get("expires_at")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                if now_dt > exp_dt:
                    logger.info(f"Trigger expired: {trigger_id}")
                    continue
            except Exception:
                pass

        try:
            result = bot.compose(category, merchant, trg, customer)
        except Exception as e:
            logger.error(f"compose() failed for {trigger_id}: {e}")
            continue

        conv_id = f"conv_{uuid.uuid4().hex[:8]}"
        merchant_id = merchant.get("merchant_id", "")
        customer_id = customer.get("customer_id") if customer else None

        # Use template for first outbound
        template_name = f"vera_{trg.get('kind', 'outbound')}_v1"
        m_name = merchant.get("identity", {}).get("owner_first_name",
                              merchant.get("identity", {}).get("name", ""))

        conversations[conv_id] = {
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "history": [{"role": "vera", "body": result["body"]}],
            "suppression_key": sup_key,
            "trigger_id": trigger_id,
        }
        suppressed.add(sup_key)

        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": result["send_as"],
            "trigger_id": trigger_id,
            "template_name": template_name,
            "template_params": [m_name, trg.get("kind", ""), ""],
            "body": result["body"],
            "cta": result["cta"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"],
        })
        logger.info(f"Tick → action for {trigger_id} (conv={conv_id})")

    return jsonify({"actions": actions})


# ---------------------------------------------------------------------------
# POST /v1/reply
# ---------------------------------------------------------------------------

AUTO_REPLY_PATTERNS = [
    "thank you for contacting",
    "thanks for reaching out",
    "aapki jaankari ke liye bahut-bahut shukriya",
    "automated assistant",
    "main ek automated",
    "i am an automated",
    "this is an automated",
    "aapki madad ke liye shukriya",
    "hum aapki madad ke liye",
]

EXIT_PATTERNS = [
    "not interested",
    "nahi chahiye", "nahi chahta", "nahi chahti",
    "band karo", "mat bhejo",
    "stop", "unsubscribe",
    "don't contact", "do not contact",
]

ACCEPT_PATTERNS = [
    "yes", "haan", "ha ", " ha\n", "ha.", "bilkul",
    "go ahead", "please do", "karo", "send it", "bhejo",
    "ok", "sure", "theek", "thik", "alright", "sounds good",
    "join karna", "judrna", "let's do", "proceed",
]

def is_auto_reply(message: str) -> bool:
    m = message.lower().strip()
    return any(p in m for p in AUTO_REPLY_PATTERNS)

def is_exit(message: str) -> bool:
    m = message.lower().strip()
    return any(p in m for p in EXIT_PATTERNS)

def is_accept(message: str) -> bool:
    m = message.lower().strip()
    return any(p in m for p in ACCEPT_PATTERNS)


@app.route("/v1/reply", methods=["POST"])
def reply():
    data = request.get_json(force=True)
    conv_id = data.get("conversation_id")
    merchant_id = data.get("merchant_id")
    customer_id = data.get("customer_id")
    from_role = data.get("from_role", "merchant")
    message = data.get("message", "")
    turn_number = data.get("turn_number", 2)

    conv = conversations.get(conv_id)
    if not conv:
        # Unknown conversation — try to respond generically
        return jsonify({
            "action": "send",
            "body": "Namaste! Aapka message mila. Kya main aapki madad kar sakti hoon?",
            "cta": "open_ended",
            "rationale": "Unknown conversation — generic response",
        })

    # Add to history
    conv["history"].append({"role": from_role, "body": message})

    # === AUTO-REPLY DETECTION ===
    if is_auto_reply(message):
        auto_reply_count = sum(1 for h in conv["history"]
                                if h["role"] != "vera" and is_auto_reply(h.get("body", "")))
        if auto_reply_count >= 2:
            # Give up gracefully
            return jsonify({
                "action": "end",
                "rationale": f"Auto-reply detected {auto_reply_count}x — graceful exit to avoid wasted turns.",
            })
        else:
            # Try once more, redirect
            reply_body = ("Samajh gayi — team tak pahunchayein. Kya aap khud 2 min mein "
                          "apna Google profile check kar sakti hain? Main exact gap dikha sakti hoon.")
            conv["history"].append({"role": "vera", "body": reply_body})
            return jsonify({
                "action": "send",
                "body": reply_body,
                "cta": "open_ended",
                "rationale": "Auto-reply detected once — single redirect attempt before exit.",
            })

    # === EXIT DETECTION ===
    if is_exit(message):
        return jsonify({
            "action": "end",
            "rationale": "Merchant expressed disinterest — graceful exit.",
        })

    # === INTENT HANDOFF (join/proceed signals) ===
    if is_accept(message) and turn_number <= 3:
        merchant = get_context("merchant", conv["merchant_id"])
        trigger_id = conv.get("trigger_id")
        trigger = get_context("trigger", trigger_id) if trigger_id else None

        if merchant and trigger:
            category = find_merchant_category(merchant)
            customer = get_context("customer", conv.get("customer_id")) if conv.get("customer_id") else None
            if category:
                try:
                    # Generate follow-up action message
                    action_trigger = dict(trigger)
                    action_trigger["kind"] = trigger.get("kind", "active_planning_intent")
                    # Inject acceptance signal into payload
                    action_trigger.setdefault("payload", {})["merchant_accepted"] = True
                    result = bot.compose(category, merchant, action_trigger, customer)
                    follow_body = result["body"]
                except Exception as e:
                    logger.error(f"Follow-up compose failed: {e}")
                    follow_body = "Bilkul! Main abhi isko set up karte hoon. Ek minute..."
            else:
                follow_body = "Bahut accha! Aapke liye draft karke bhejti hoon abhi."
        else:
            follow_body = "Bahut accha! Aapke liye draft karke bhejti hoon abhi."

        conv["history"].append({"role": "vera", "body": follow_body})
        return jsonify({
            "action": "send",
            "body": follow_body,
            "cta": "open_ended",
            "rationale": "Merchant accepted — routing to action immediately, no re-qualification.",
        })

    # === GENERAL FOLLOW-UP ===
    # Build a contextual follow-up using the merchant's data
    merchant = get_context("merchant", conv["merchant_id"])
    trigger_id = conv.get("trigger_id")
    trigger = get_context("trigger", trigger_id) if trigger_id else None

    if merchant and trigger:
        category = find_merchant_category(merchant)
        customer = get_context("customer", conv.get("customer_id")) if conv.get("customer_id") else None
        if category:
            try:
                # Contextual reply — include the merchant's message in payload
                reply_trigger = dict(trigger)
                reply_trigger.setdefault("payload", {})["merchant_reply"] = message
                reply_trigger["kind"] = "active_planning_intent"
                result = bot.compose(category, merchant, reply_trigger, customer)
                reply_body = result["body"]
                conv["history"].append({"role": "vera", "body": reply_body})
                return jsonify({
                    "action": "send",
                    "body": reply_body,
                    "cta": result["cta"],
                    "rationale": f"Contextual follow-up to merchant reply: '{message[:50]}'",
                })
            except Exception as e:
                logger.error(f"Reply compose failed: {e}")

    # Fallback
    fallback = "Samajh gayi! Main isko dekhti hoon aur aapko update karti hoon."
    conv["history"].append({"role": "vera", "body": fallback})
    return jsonify({
        "action": "send",
        "body": fallback,
        "cta": "open_ended",
        "rationale": "Fallback contextual response.",
    })


# ---------------------------------------------------------------------------
# GET /v1/healthz
# ---------------------------------------------------------------------------

@app.route("/v1/healthz", methods=["GET"])
def healthz():
    counts = {scope: len(v) for scope, v in contexts.items()}
    return jsonify({
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME),
        "contexts_loaded": counts,
    })


# ---------------------------------------------------------------------------
# GET /v1/metadata
# ---------------------------------------------------------------------------

@app.route("/v1/metadata", methods=["GET"])
def metadata():
    return jsonify({
        "team_name": "Vera Decision Engine",
        "team_members": ["Manorama"],
        "model": "claude-sonnet-4-20250514",
        "approach": (
            "3-layer architecture: (1) pure-logic decision engine selects intent, CTA shape, "
            "and compulsion levers per trigger kind; (2) context builder assembles grounded "
            "fact block — only verified numbers from the 4 contexts, no hallucination; "
            "(3) Claude at temperature=0 composes the final message constrained strictly to "
            "the fact block. Auto-reply detection, intent handoff, and graceful exit are "
            "handled as deterministic routing rules, not LLM guesses."
        ),
        "contact_email": "participant@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    logger.info(f"Starting Vera bot on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)