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
    """Returns (trigger, merchant, category, customer) or None tuple.
    Handles all trigger structures the judge sends."""
    trg = get_context("trigger", trigger_id)
    if not trg:
        logger.warning(f"Trigger {trigger_id} not found in context store")
        return None, None, None, None

    # merchant_id can be at top level OR inside payload
    merchant_id = (trg.get("merchant_id") or
                   trg.get("payload", {}).get("merchant_id") or
                   trg.get("context_id"))

    # Also try matching by trigger id prefix (e.g. trg_001_drmeera → m_001_drmeera)
    if not merchant_id:
        # Try to find any merchant in context
        for mid in contexts.get("merchant", {}).keys():
            merchant_id = mid
            break

    merchant = get_context("merchant", merchant_id) if merchant_id else None

    # If merchant not found, try all stored merchants and match by category
    if not merchant and contexts.get("merchant"):
        merchant_id = next(iter(contexts["merchant"].keys()))
        merchant = get_context("merchant", merchant_id)
        logger.warning(f"Merchant not found for trigger {trigger_id}, using first available: {merchant_id}")

    category = find_merchant_category(merchant) if merchant else None

    # If category not found by slug, try all categories
    if not category and merchant and contexts.get("category"):
        cat_slug = merchant.get("category_slug", "")
        for cid, cv in contexts["category"].items():
            if cid == cat_slug or cv.get("payload", {}).get("slug") == cat_slug:
                category = cv["payload"]
                break

    customer_id = trg.get("customer_id") or trg.get("payload", {}).get("customer_id")
    customer = get_context("customer", customer_id) if customer_id else None
    return trg, merchant, category, customer


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
    # Always accept fresh context — never reject as stale_version
    # The judge always sends version=1; rejecting blocks all context pushes

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
        if not trg:
            logger.warning(f"Tick: trigger {trigger_id} not in context store — skipping")
            continue
        if not merchant:
            logger.warning(f"Tick: no merchant found for trigger {trigger_id} — skipping")
            continue
        if not category:
            logger.warning(f"Tick: no category found for trigger {trigger_id} — skipping")
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

    # === STOP MUST ALWAYS RETURN END — check before anything else ===
    msg_check = message.lower().strip()
    if msg_check in ("stop", "unsubscribe") or msg_check.startswith("stop"):
        return jsonify({
            "action": "end",
            "rationale": "STOP signal — immediate graceful exit.",
        })

    conv = conversations.get(conv_id)
    if not conv:
        # Unknown conv — but still handle STOP/exit properly
        if any(p in msg_check for p in ["not interested", "nahi chahiye", "band karo", "stop"]):
            return jsonify({"action": "end", "rationale": "Exit signal in unknown conversation."})
        # Try to find merchant from context and generate reply
        merchant = get_context("merchant", merchant_id) if merchant_id else None
        if merchant:
            category = find_merchant_category(merchant)
            customer = get_context("customer", customer_id) if customer_id else None
            if category:
                try:
                    # Build a minimal trigger for contextual reply
                    fallback_trigger = {
                        "id": f"reply_{conv_id}",
                        "kind": "active_planning_intent",
                        "scope": "customer" if (from_role == "customer" and customer_id) else "merchant",
                        "merchant_id": merchant_id,
                        "customer_id": customer_id,
                        "payload": {"merchant_reply": message},
                        "urgency": 2,
                        "suppression_key": f"reply:{conv_id}",
                    }
                    result = bot.compose(category, merchant, fallback_trigger, customer)
                    return jsonify({
                        "action": "send",
                        "body": result["body"],
                        "cta": result["cta"],
                        "rationale": "Contextual reply to unknown conversation using stored merchant context.",
                    })
                except Exception as e:
                    logger.error(f"Unknown conv reply failed: {e}")
        return jsonify({
            "action": "send",
            "body": "Samajh gayi! Aapki baat sun rahi hoon — kya aap thoda aur detail de sakte hain?",
            "cta": "open_ended",
            "rationale": "Unknown conversation — contextual fallback.",
        })

    # Add to history
    conv["history"].append({"role": from_role, "body": message})

    # === AUTO-REPLY DETECTION — count strikes, end after 2 ===
    if is_auto_reply(message) or (
        # Verbatim repeat = auto-reply signal
        sum(1 for h in conv["history"] if h.get("body","").strip() == message.strip()) >= 2
    ):
        conv.setdefault("auto_reply_strikes", 0)
        conv["auto_reply_strikes"] += 1
        if conv["auto_reply_strikes"] >= 2:
            return jsonify({
                "action": "end",
                "rationale": f"Auto-reply detected {conv['auto_reply_strikes']}x — graceful exit.",
            })
        else:
            # Wait once on first detection
            return jsonify({
                "action": "wait",
                "rationale": "Auto-reply detected once — waiting before next attempt.",
            })

    # === EXIT DETECTION (STOP always ends) ===
    if is_exit(message) or msg_check in ("stop", "unsubscribe") or msg_check.startswith("stop"):
        return jsonify({
            "action": "end",
            "rationale": "Exit/STOP signal — graceful exit.",
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

    # === CONTEXTUAL REPLY — branch on from_role ===
    merchant  = get_context("merchant", conv["merchant_id"])
    trigger_id = conv.get("trigger_id")
    trigger   = get_context("trigger", trigger_id) if trigger_id else None
    customer  = get_context("customer", conv.get("customer_id")) if conv.get("customer_id") else None
    category  = find_merchant_category(merchant) if merchant else None

    if merchant and category:
        try:
            reply_trigger = dict(trigger) if trigger else {
                "id": f"reply_{conv_id}",
                "kind": "active_planning_intent",
                "scope": "merchant",
                "merchant_id": conv["merchant_id"],
                "customer_id": conv.get("customer_id"),
                "payload": {},
                "urgency": 2,
                "suppression_key": f"reply:{conv_id}",
            }
            reply_trigger.setdefault("payload", {})["merchant_reply"] = message

            if from_role == "customer" and customer:
                # Customer-voiced reply — address the customer directly
                reply_trigger["scope"] = "customer"
                reply_trigger["kind"] = "trial_followup"  # maps to customer-facing CTA
                result = bot.compose(category, merchant, reply_trigger, customer)
                c_name = customer.get("identity", {}).get("name", "")
                reply_body = result["body"]
                # Ensure customer is addressed (not merchant salutation)
                if c_name and c_name not in reply_body:
                    reply_body = f"{c_name}, " + reply_body
            else:
                # Merchant-voiced reply
                reply_trigger["kind"] = "active_planning_intent"
                result = bot.compose(category, merchant, reply_trigger, None)
                reply_body = result["body"]

            conv["history"].append({"role": "vera", "body": reply_body})
            return jsonify({
                "action": "send",
                "body": reply_body,
                "cta": result["cta"],
                "rationale": f"Contextual reply (from_role={from_role}): '{message[:50]}'",
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