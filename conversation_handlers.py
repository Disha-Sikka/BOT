"""
conversation_handlers.py — Multi-turn conversation state machine
Optional tiebreaker component for the magicpin AI Challenge.

Handles:
  - Auto-reply detection (same message verbatim 3+ times = auto-reply)
  - Intent routing (accept → action; decline → graceful exit)
  - Conversation pacing (don't re-send what was just sent)
  - Language detection per turn
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional, Literal

# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------

@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    trigger_id: str
    trigger_kind: str

    history: list = field(default_factory=list)  # {"role": "vera"|"merchant", "body": str}
    merchant_reply_count: int = 0
    auto_reply_strikes: int = 0
    status: Literal["active", "waiting", "ended"] = "active"
    last_vera_cta: str = "open_ended"
    context_snapshot: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# DETECTION
# ---------------------------------------------------------------------------

AUTO_REPLY_SIGNALS = [
    r"thank\s*you\s*for\s*contact",
    r"thanks\s*for\s*reach",
    r"automated\s*assistant",
    r"main\s*ek\s*automated",
    r"i\s*am\s*an\s*automated",
    r"aapki\s*jaankari\s*ke\s*liye.*shukriya",
    r"aapki\s*madad\s*ke\s*liye\s*shukriya",
    r"hum\s*aapki\s*madad",
    r"banda\s*hai",
    r"main.*automated",
]

EXIT_SIGNALS = [
    r"\bnot\s*interested\b",
    r"\bnahi\s*chahiye\b",
    r"\bband\s*karo\b",
    r"\bmat\s*bhejo\b",
    r"\bstop\b",
    r"\bunsubscribe\b",
    r"\bdo\s*not\s*contact\b",
    r"\bdonut\s*contact\b",
]

ACCEPT_SIGNALS = [
    r"\byes\b",
    r"\bhaan\b",
    r"\bha\b",
    r"\bbilkul\b",
    r"\bgo\s*ahead\b",
    r"\bplease\s*do\b",
    r"\bkaro\b",
    r"\bsend\s*it\b",
    r"\bbhejo\b",
    r"\bok\b",
    r"\bsure\b",
    r"\btheek\b",
    r"\bthik\b",
    r"\balright\b",
    r"\bsounds\s*good\b",
    r"\bproceed\b",
    r"\blet'?s\s*do\b",
    r"\bjoin\s*karna\b",
    r"\bjudrna\b",
]

HINDI_PATTERN = re.compile(r'[\u0900-\u097F]')


def is_auto_reply(message: str) -> bool:
    m = message.lower().strip()
    return any(re.search(p, m) for p in AUTO_REPLY_SIGNALS)


def is_exit(message: str) -> bool:
    m = message.lower().strip()
    return any(re.search(p, m) for p in EXIT_SIGNALS)


def is_accept(message: str) -> bool:
    m = message.lower().strip()
    return any(re.search(p, m) for p in ACCEPT_SIGNALS)


def detect_language(message: str) -> str:
    """Returns 'hi', 'en', or 'hi_en_mix'."""
    has_hindi = bool(HINDI_PATTERN.search(message))
    has_english = bool(re.search(r'[a-zA-Z]', message))
    if has_hindi and has_english:
        return "hi_en_mix"
    elif has_hindi:
        return "hi"
    return "en"


def is_verbatim_repeat(state: ConversationState, message: str) -> bool:
    """Check if same message appeared 3+ times (strong auto-reply signal)."""
    merchant_messages = [h["body"] for h in state.history
                         if h["role"] in ("merchant", "customer")]
    return merchant_messages.count(message.strip()) >= 2  # this + 2 prior = 3 total


# ---------------------------------------------------------------------------
# RESPONSE LOGIC
# ---------------------------------------------------------------------------

def respond(state: ConversationState, merchant_message: str) -> dict:
    """
    Given conversation state + merchant's latest message, return next action.

    Returns dict with:
      action: "send" | "wait" | "end"
      body: str (if action == "send")
      cta: str
      rationale: str
    """

    # Record the incoming message
    state.history.append({"role": "merchant", "body": merchant_message})
    state.merchant_reply_count += 1
    detected_lang = detect_language(merchant_message)

    # -----------------------------------------------------------------------
    # 1. VERBATIM REPEAT → strong auto-reply
    # -----------------------------------------------------------------------
    if is_verbatim_repeat(state, merchant_message):
        state.auto_reply_strikes += 1
        if state.auto_reply_strikes >= 2:
            state.status = "ended"
            return {
                "action": "end",
                "rationale": "Same message sent 3+ times — confirmed auto-reply. Graceful exit.",
            }

    # -----------------------------------------------------------------------
    # 2. AUTO-REPLY PATTERNS
    # -----------------------------------------------------------------------
    if is_auto_reply(merchant_message):
        state.auto_reply_strikes += 1
        if state.auto_reply_strikes >= 2:
            state.status = "ended"
            return {
                "action": "end",
                "rationale": "Auto-reply pattern detected twice. Graceful exit.",
            }
        # One more try — redirect
        body = _redirect_after_auto_reply(state, detected_lang)
        state.history.append({"role": "vera", "body": body})
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": "Auto-reply detected once — redirecting to direct engagement attempt.",
        }

    # Reset auto-reply strike if real reply detected
    state.auto_reply_strikes = 0

    # -----------------------------------------------------------------------
    # 3. EXIT SIGNALS
    # -----------------------------------------------------------------------
    if is_exit(merchant_message):
        state.status = "ended"
        farewell = _farewell(state, detected_lang)
        state.history.append({"role": "vera", "body": farewell})
        return {
            "action": "end",
            "rationale": "Merchant signalled disinterest — graceful exit with positive note.",
        }

    # -----------------------------------------------------------------------
    # 4. EXPLICIT ACCEPT → immediate action, no re-qualification
    # -----------------------------------------------------------------------
    if is_accept(merchant_message) and state.merchant_reply_count <= 3:
        body = _action_response(state, detected_lang)
        state.history.append({"role": "vera", "body": body})
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": "Merchant accepted — routing to action immediately, zero re-qualification.",
        }

    # -----------------------------------------------------------------------
    # 5. QUESTION / CURIOSITY from merchant
    # -----------------------------------------------------------------------
    if "?" in merchant_message or any(w in merchant_message.lower()
                                       for w in ["kya", "kaise", "kitna", "when", "how", "what"]):
        body = _answer_question(state, merchant_message, detected_lang)
        state.history.append({"role": "vera", "body": body})
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": "Merchant asked a question — direct answer with next step.",
        }

    # -----------------------------------------------------------------------
    # 6. GENERAL REPLY
    # -----------------------------------------------------------------------
    body = _general_followup(state, detected_lang)
    state.history.append({"role": "vera", "body": body})
    return {
        "action": "send",
        "body": body,
        "cta": "open_ended",
        "rationale": "General reply — advancing the conversation with next specific step.",
    }


# ---------------------------------------------------------------------------
# RESPONSE BUILDERS (specific, grounded)
# ---------------------------------------------------------------------------

def _get_merchant_name(state: ConversationState) -> str:
    merchant = state.context_snapshot.get("merchant", {})
    return merchant.get("identity", {}).get("owner_first_name",
           merchant.get("identity", {}).get("name", ""))


def _redirect_after_auto_reply(state: ConversationState, lang: str) -> str:
    merchant = state.context_snapshot.get("merchant", {})
    cat_slug = merchant.get("category_slug", "")
    name = _get_merchant_name(state)

    if "hi" in lang:
        return (f"Samajh gayi — team ko forward ho gaya. Kya aap khud directly dekh sakte hain "
                f"Google pe kya missing hai? 2 minute ka kaam hai. Chalega?")
    return (f"Got it — passing to your team. Quick check: want to see what's missing on your "
            f"Google listing? Takes 2 min and I can walk you through it.")


def _farewell(state: ConversationState, lang: str) -> str:
    merchant = state.context_snapshot.get("merchant", {})
    name = _get_merchant_name(state)
    if "hi" in lang:
        return f"Koi baat nahi {name}! Aapka kaam accha chal raha hai — best wishes. 🙂"
    return f"No worries, {name}! Best wishes for your business. 🙂"


def _action_response(state: ConversationState, lang: str) -> str:
    kind = state.trigger_kind
    merchant = state.context_snapshot.get("merchant", {})
    name = _get_merchant_name(state)
    cat_slug = merchant.get("category_slug", "")

    action_map = {
        "research_digest": (
            "Accha! Main JIDA abstract pull karke aur ek ready-to-share patient WhatsApp draft karti hoon — "
            "10 minute mein bhejti hoon." if "hi" in lang else
            "Great! Pulling the JIDA abstract now + drafting a patient-ed WhatsApp you can forward. Sending in 10 min."
        ),
        "recall_due": (
            "Perfect! Appointment slot block kar rahi hoon. Confirm ho jayega SMS se." if "hi" in lang else
            "Done! Booking the slot now — you'll get an SMS confirmation shortly."
        ),
        "festival_upcoming": (
            "Bilkul! Diwali campaign draft kar rahi hoon — content + timing. Review ke liye 15 min mein aayega." if "hi" in lang else
            "On it! Drafting the Diwali campaign — content + schedule. Review copy coming in 15 min."
        ),
        "perf_dip": (
            "Theek hai, 3 quick fixes identify kar rahi hoon. Ek kaam ab — profile verification complete karte hain." if "hi" in lang else
            "Got it. Identifying 3 quick fixes. First action — let's complete your profile verification right now."
        ),
        "gbp_unverified": (
            "Chaliye! Verification process start karte hain abhi. Aapko ek postcard ya phone call aayega Google se." if "hi" in lang else
            "Let's go! Starting the verification process now. You'll get a postcard or phone call from Google."
        ),
    }
    return action_map.get(kind,
        ("Shuruaat karte hain! Aapke liye draft karti hoon — 10-15 min mein update deti hoon." if "hi" in lang else
         "Starting now! Drafting your materials — update in 10-15 min."))


def _answer_question(state: ConversationState, question: str, lang: str) -> str:
    kind = state.trigger_kind
    merchant = state.context_snapshot.get("merchant", {})
    perf = merchant.get("performance", {})
    cat = state.context_snapshot.get("category", {})
    peer = cat.get("peer_stats", {})

    if "ctr" in question.lower() or "views" in question.lower():
        m_ctr = perf.get("ctr", 0)
        p_ctr = peer.get("avg_ctr", 0)
        if "hi" in lang:
            return (f"Aapka CTR abhi {m_ctr*100:.1f}% hai. Area median {p_ctr*100:.1f}% hai — "
                    f"gap {(p_ctr-m_ctr)*100:.1f}pp ka hai. Profile photos + recent posts se "
                    f"typically 0.5-1pp improvement hota hai.")
        return (f"Your CTR is currently {m_ctr*100:.1f}% vs area median {p_ctr*100:.1f}%. "
                f"Gap is {(p_ctr-m_ctr)*100:.1f}pp. Profile photos + recent posts typically close 0.5-1pp.")

    # Generic informative response
    if "hi" in lang:
        return "Accha sawaal! Let me check that for you — ek minute. Main exact numbers ke saath wapas aati hoon."
    return "Good question! Let me check that for you — one moment. I'll come back with the exact numbers."


def _general_followup(state: ConversationState, lang: str) -> str:
    kind = state.trigger_kind
    merchant = state.context_snapshot.get("merchant", {})
    name = _get_merchant_name(state)
    turn = state.merchant_reply_count

    # After 3 real turns, nudge toward a concrete action
    if turn >= 3:
        if "hi" in lang:
            return f"Theek hai {name}! Kya main ek specific cheez set up kar sakti hoon aapke liye abhi — bilkul ready, sirf aapka go chahiye?"
        return f"Got it, {name}! Can I set up one specific thing for you right now — completely ready, just need your go-ahead?"

    if "hi" in lang:
        return "Samajh gayi. Koi aur sawal ho ya directly start karte hain?"
    return "Understood. Any other questions or shall we get started directly?"