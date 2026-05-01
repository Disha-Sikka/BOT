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
        <a class="card" href="/demo" style="border-color:#0f4539;background:#f0fdf4;">
            <h3><span class="method get" style="background:#dcfce7;color:#15803d;">GET</span> /demo</h3>
            <p>🔬 Interactive API explorer — test all endpoints in browser</p>
        </a>
        <a class="card" href="/chat" style="border-color:#25d366;background:#f0fff4;">
            <h3><span class="method get" style="background:#dcfce7;color:#15803d;">GET</span> /chat</h3>
            <p>💬 Talk to Vera like a real merchant — WhatsApp style</p>
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
    """Generates a real message live using hardcoded seed data."""
    import json

    # Hardcoded minimal seed — no dataset folder needed on server
    dentists = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "salutation": "Dr. {first_name}", "vocab_no": ["guaranteed", "100% safe"]},
        "offer_catalog": [{"title": "Dental Cleaning @ ₹299"}, {"title": "Teeth Whitening @ ₹1,499"}],
        "peer_stats": {"avg_ctr": 0.030, "avg_rating": 4.4, "avg_review_count": 62, "avg_views_30d": 1820},
        "digest": [{"id": "d_2026W17_jida_fluoride", "source": "JIDA Oct 2026, p.14",
                    "title": "3-month fluoride recall cuts caries 38% better than 6-month",
                    "trial_n": 2100, "patient_segment": "high_risk_adults",
                    "summary": "Multi-center Indian trial: 38% lower caries recurrence with 3-month vs 6-month recall in high-risk adults."}],
        "seasonal_beats": [{"month_range": "Oct-Dec", "note": "wedding whitening peak"}],
        "trend_signals": [{"query": "clear aligners delhi", "delta_yoy": 0.62}],
    }
    merchant = {
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera",
                     "city": "Delhi", "locality": "Lajpat Nagar",
                     "languages": ["en", "hi"], "verified": True},
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021, "leads": 9,
                        "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05, "ctr_pct": 0.02}},
        "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
        "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort"],
        "customer_aggregate": {"total_unique_ytd": 540, "lapsed_180d_plus": 78,
                               "retention_6mo_pct": 0.38, "high_risk_adult_count": 124},
        "review_themes": [{"theme": "wait_time", "sentiment": "neg", "occurrences_30d": 3,
                           "common_quote": "had to wait 30 min on Sunday"}],
        "conversation_history": [],
    }
    trigger = {
        "id": "trg_001_research_digest_dentists",
        "scope": "merchant", "kind": "research_digest", "source": "external",
        "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
        "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
        "urgency": 2, "suppression_key": "research:dentists:2026-W17",
    }

    try:
        result   = bot.compose(dentists, merchant, trigger, customer=None)
        body     = result["body"]
        cta      = result["cta"]
        send_as  = result["send_as"]
        rationale = result["rationale"]
        status   = "success"
        error    = ""
    except Exception as e:
        body = rationale = cta = send_as = ""
        status = "error"
        error  = str(e)

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
# GET /chat — WhatsApp-style chat interface to talk to Vera
# ---------------------------------------------------------------------------

@app.route("/chat", methods=["GET"])
def chat_page():
    return """<!DOCTYPE html>
<html>
<head>
    <title>Chat with Vera</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #e5ddd5; height: 100vh; display: flex; flex-direction: column; }

        .topbar { background: #075e54; color: white; padding: 12px 16px; display: flex; align-items: center; gap: 12px; }
        .avatar { width: 40px; height: 40px; border-radius: 50%; background: #25d366; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 16px; }
        .topbar-info h2 { font-size: 15px; font-weight: 600; }
        .topbar-info p { font-size: 12px; opacity: 0.8; }
        .status-dot { width: 8px; height: 8px; background: #25d366; border-radius: 50%; display: inline-block; margin-right: 4px; }

        .merchant-bar { background: #f0f0f0; padding: 8px 16px; font-size: 12px; color: #555; border-bottom: 1px solid #ddd; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
        .merchant-bar select, .merchant-bar button { font-size: 12px; padding: 4px 10px; border-radius: 6px; border: 1px solid #ccc; background: white; cursor: pointer; }
        .merchant-bar button { background: #075e54; color: white; border: none; }

        .messages { flex: 1; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }

        .msg { max-width: 75%; padding: 8px 12px; border-radius: 10px; font-size: 14px; line-height: 1.5; position: relative; }
        .msg .time { font-size: 10px; opacity: 0.6; margin-top: 4px; text-align: right; }
        .msg.vera { background: white; align-self: flex-start; border-top-left-radius: 2px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
        .msg.merchant { background: #dcf8c6; align-self: flex-end; border-top-right-radius: 2px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
        .msg.system { background: rgba(0,0,0,0.08); align-self: center; font-size: 11px; color: #555; border-radius: 8px; padding: 4px 12px; max-width: 90%; text-align: center; }
        .sender { font-size: 11px; font-weight: bold; color: #075e54; margin-bottom: 2px; }
        .typing { background: white; align-self: flex-start; border-radius: 10px; padding: 10px 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
        .typing span { display: inline-block; width: 8px; height: 8px; background: #aaa; border-radius: 50%; margin: 0 2px; animation: bounce 1.2s infinite; }
        .typing span:nth-child(2) { animation-delay: 0.2s; }
        .typing span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-6px)} }

        .input-bar { background: #f0f0f0; padding: 10px 12px; display: flex; gap: 8px; align-items: center; }
        .input-bar input { flex: 1; padding: 10px 14px; border-radius: 20px; border: none; font-size: 14px; outline: none; }
        .input-bar button { width: 42px; height: 42px; border-radius: 50%; background: #075e54; color: white; border: none; cursor: pointer; font-size: 18px; display: flex; align-items: center; justify-content: center; }
        .input-bar button:hover { background: #064c44; }

        .cta-buttons { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
        .cta-btn { background: #075e54; color: white; border: none; padding: 6px 14px; border-radius: 16px; font-size: 13px; cursor: pointer; }
        .cta-btn.stop { background: #e74c3c; }
        .cta-btn:hover { opacity: 0.85; }
    </style>
</head>
<body>

<div class="topbar">
    <div class="avatar">V</div>
    <div class="topbar-info">
        <h2>Vera <span style="font-size:11px;opacity:0.7">by magicpin</span></h2>
        <p><span class="status-dot"></span>online</p>
    </div>
</div>

<div class="merchant-bar">
    <span>You are:</span>
    <select id="merchant-select" onchange="changeMerchant()">
        <option value="dentist">Dr. Meera — Dental Clinic, Delhi</option>
        <option value="salon">Lakshmi — Studio11 Salon, Hyderabad</option>
        <option value="restaurant">Suresh — SK Pizza Junction, Delhi</option>
        <option value="gym">Kiran — PowerHouse Fitness, Bangalore</option>
    </select>
    <button onclick="startConversation()">Start fresh chat</button>
</div>

<div class="messages" id="messages">
    <div class="msg system">Loading Vera...</div>
</div>

<div class="input-bar">
    <input type="text" id="msg-input" placeholder="Type a message..." onkeydown="if(event.key==='Enter') sendMsg()">
    <button onclick="sendMsg()">➤</button>
</div>

<script>
const MERCHANTS = {
    dentist: {
        merchant: {merchant_id:"m_demo_dentist",category_slug:"dentists",identity:{name:"Dr. Meera Dental Clinic",owner_first_name:"Meera",city:"Delhi",locality:"Lajpat Nagar",languages:["en","hi"],verified:true},performance:{views:2410,calls:18,ctr:0.021,leads:9,delta_7d:{views_pct:0.18,calls_pct:-0.05,ctr_pct:0.02}},offers:[{title:"Dental Cleaning @ ₹299",status:"active"}],signals:["ctr_below_peer_median","stale_posts:22d","high_risk_adult_cohort"],subscription:{status:"active",plan:"Pro",days_remaining:82},customer_aggregate:{total_unique_ytd:540,lapsed_180d_plus:78,retention_6mo_pct:0.38,high_risk_adult_count:124},review_themes:[],conversation_history:[]},
        category: {slug:"dentists",voice:{tone:"peer_clinical",salutation:"Dr. {first_name}",vocab_no:["guaranteed"]},offer_catalog:[{title:"Dental Cleaning @ ₹299"},{title:"Teeth Whitening @ ₹1,499"}],peer_stats:{avg_ctr:0.03,avg_rating:4.4,avg_review_count:62,avg_views_30d:1820},digest:[{id:"d_jida",source:"JIDA Oct 2026 p.14",title:"3-month fluoride recall cuts caries 38% vs 6-month",trial_n:2100,patient_segment:"high_risk_adults",summary:"38% lower caries recurrence with 3-month recall in high-risk adults."}],seasonal_beats:[],trend_signals:[]},
        trigger: {id:"trg_demo_dentist",scope:"merchant",kind:"research_digest",source:"external",merchant_id:"m_demo_dentist",customer_id:null,payload:{category:"dentists",top_item_id:"d_jida"},urgency:2,suppression_key:"demo:dentist:research",expires_at:"2026-12-01T00:00:00Z"},
        name: "Dr. Meera"
    },
    salon: {
        merchant: {merchant_id:"m_demo_salon",category_slug:"salons",identity:{name:"Studio11 Family Salon",owner_first_name:"Lakshmi",city:"Hyderabad",locality:"Kapra",languages:["en","hi","te"],verified:true},performance:{views:5430,calls:61,ctr:0.041,leads:38,delta_7d:{views_pct:0.12,calls_pct:0.2,ctr_pct:0.03}},offers:[{title:"Bridal Package @ ₹24,999",status:"active"},{title:"Keratin Treatment @ ₹3,499",status:"active"}],signals:["strong_performer","bridal_peak_incoming"],subscription:{status:"active",plan:"Pro",days_remaining:142},customer_aggregate:{total_unique_ytd:1240,lapsed_180d_plus:180,retention_6mo_pct:0.62},review_themes:[],conversation_history:[]},
        category: {slug:"salons",voice:{tone:"warm_practical",salutation:"{first_name}",vocab_no:["guaranteed results"]},offer_catalog:[{title:"Bridal Package @ ₹24,999"},{title:"Keratin Treatment @ ₹3,499"},{title:"Haircut @ ₹299"}],peer_stats:{avg_ctr:0.038,avg_rating:4.2,avg_review_count:85,avg_views_30d:3200},digest:[{id:"d_diwali",source:"magicpin salon data 2025",title:"Diwali: 3x weekend footfall, advance booking critical",trial_n:null,patient_segment:null,summary:"Pre-Diwali bridal and party bookings surge. Walk-in overflow causes wait complaints."}],seasonal_beats:[{month_range:"Oct-Nov",note:"Diwali bridal peak"}],trend_signals:[]},
        trigger: {id:"trg_demo_salon",scope:"merchant",kind:"festival_upcoming",source:"external",merchant_id:"m_demo_salon",customer_id:null,payload:{festival:"Diwali",days_until:5},urgency:3,suppression_key:"demo:salon:diwali",expires_at:"2026-12-01T00:00:00Z"},
        name: "Lakshmi"
    },
    restaurant: {
        merchant: {merchant_id:"m_demo_restaurant",category_slug:"restaurants",identity:{name:"SK Pizza Junction",owner_first_name:"Suresh",city:"Delhi",locality:"Sant Nagar",languages:["en","hi"],verified:true},performance:{views:3100,calls:22,ctr:0.033,leads:18,delta_7d:{views_pct:0.05,calls_pct:-0.1,ctr_pct:0.01}},offers:[{title:"BOGO Pizza Tue-Thu",status:"active"}],signals:["trial_expiring_soon","delivery_preference"],subscription:{status:"trial",plan:"Trial",days_remaining:8},customer_aggregate:{total_unique_ytd:920,lapsed_180d_plus:310,retention_6mo_pct:0.44},review_themes:[{theme:"delivery_time",sentiment:"neg",occurrences_30d:5,common_quote:"delivery took 45 min"}],conversation_history:[]},
        category: {slug:"restaurants",voice:{tone:"friendly_operator",salutation:"{first_name}",vocab_no:[]},offer_catalog:[{title:"BOGO Pizza Tue-Thu"},{title:"Family Combo @ ₹699"}],peer_stats:{avg_ctr:0.036,avg_rating:4.1,avg_review_count:120,avg_views_30d:3800},digest:[{id:"d_ipl",source:"magicpin restaurant data 2025",title:"Saturday IPL home matches shift -12% restaurant covers",trial_n:null,patient_segment:null,summary:"When IPL home matches fall on Saturday, dine-in covers drop 12%. Push delivery instead."}],seasonal_beats:[],trend_signals:[]},
        trigger: {id:"trg_demo_restaurant",scope:"merchant",kind:"review_theme_emerged",source:"internal",merchant_id:"m_demo_restaurant",customer_id:null,payload:{theme:"delivery_time",occurrences_30d:5,common_quote:"delivery took 45 min"},urgency:3,suppression_key:"demo:restaurant:reviews",expires_at:"2026-12-01T00:00:00Z"},
        name: "Suresh"
    },
    gym: {
        merchant: {merchant_id:"m_demo_gym",category_slug:"gyms",identity:{name:"PowerHouse Fitness",owner_first_name:"Kiran",city:"Bangalore",locality:"Indiranagar",languages:["en","hi"],verified:true},performance:{views:2800,calls:19,ctr:0.029,leads:14,delta_7d:{views_pct:-0.18,calls_pct:-0.25,ctr_pct:-0.08}},offers:[{title:"3-Month Membership @ ₹4,999",status:"active"},{title:"Personal Training Trial @ ₹999",status:"active"}],signals:["seasonal_dip_expected","perf_dip_moderate"],subscription:{status:"active",plan:"Pro",days_remaining:88},customer_aggregate:{total_unique_ytd:480,lapsed_180d_plus:165,retention_6mo_pct:0.42},review_themes:[],conversation_history:[]},
        category: {slug:"gyms",voice:{tone:"energetic_peer",salutation:"{first_name}",vocab_no:["guaranteed weight loss"]},offer_catalog:[{title:"3-Month Membership @ ₹4,999"},{title:"Student Morning Batch @ ₹2,499"}],peer_stats:{avg_ctr:0.032,avg_rating:4.3,avg_review_count:48,avg_views_30d:2200},digest:[{id:"d_exam",source:"magicpin gym data 2026",title:"Exam season causes 18-22% enrollment dip April-May",trial_n:null,patient_segment:"student_18_24",summary:"Gyms running student morning batch offers offset 60-70% of seasonal dip."}],seasonal_beats:[{month_range:"Apr-May",note:"exam season dip"}],trend_signals:[]},
        trigger: {id:"trg_demo_gym",scope:"merchant",kind:"seasonal_perf_dip",source:"internal",merchant_id:"m_demo_gym",customer_id:null,payload:{metric:"views",delta_pct:-0.30,season_note:"exam_season"},urgency:2,suppression_key:"demo:gym:seasonal",expires_at:"2026-12-01T00:00:00Z"},
        name: "Kiran"
    }
};

let currentMerchant = "dentist";
let convId = null;
let turnNumber = 1;
let initialized = false;

function now() {
    return new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}

function addMsg(text, role, showCTA) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    if (role === 'vera') {
        div.innerHTML = '<div class="sender">Vera</div>' + text.replace(/\n/g,'<br>');
        if (showCTA) {
            div.innerHTML += '<div class="cta-buttons"><button class="cta-btn" onclick="sendQuick(\'YES\')">YES</button><button class="cta-btn stop" onclick="sendQuick(\'STOP\')">STOP</button><button class="cta-btn" onclick="sendQuick(\'Tell me more\')">Tell me more</button></div>';
        }
    } else if (role === 'merchant') {
        div.innerHTML = text;
    } else {
        div.innerHTML = text;
    }
    div.innerHTML += '<div class="time">' + now() + (role==='merchant'?' ✓✓':'') + '</div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function addSystem(text) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'msg system';
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function showTyping() {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'typing';
    div.id = 'typing-indicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function hideTyping() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

async function pushContext(scope, id, payload) {
    await fetch('/v1/context', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({scope, context_id: id, version: Math.floor(Date.now()/1000), payload, delivered_at: new Date().toISOString()})
    });
}

async function startConversation() {
    convId = null;
    turnNumber = 1;
    initialized = false;
    document.getElementById('messages').innerHTML = '';
    addSystem('Starting conversation...');

    const m = MERCHANTS[currentMerchant];
    addSystem('Connecting to Vera via Mistral AI (10-20s)...');
    showTyping();

    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 55000);

        const tickRes = await fetch('/v1/chat_message', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({category: m.category, merchant: m.merchant, trigger: m.trigger, customer: null}),
            signal: controller.signal
        });
        clearTimeout(timeout);
        const action = await tickRes.json();
        hideTyping();

        if (action.error) {
            document.getElementById('messages').innerHTML = '';
            addSystem('Error: ' + action.error + ' — Click Start fresh chat.');
        } else {
            convId = 'conv_' + Date.now();
            const isBinary = action.cta === 'binary_yes_stop';
            document.getElementById('messages').innerHTML = '';
            addMsg(action.body, 'vera', isBinary);
            initialized = true;
        }
    } catch(e) {
        hideTyping();
        document.getElementById('messages').innerHTML = '';
        if (e.name === 'AbortError') {
            addSystem('Vera is taking too long (Mistral API slow). Click "Start fresh chat" to retry.');
        } else {
            addSystem('Error: ' + e.message + ' — Click "Start fresh chat" to retry.');
        }
    }
}

async function sendMsg() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text || !initialized) return;
    input.value = '';

    addMsg(text, 'merchant');
    turnNumber++;
    showTyping();

    try {
        const ctrl2 = new AbortController();
        const t2 = setTimeout(() => ctrl2.abort(), 55000);
        const m2 = MERCHANTS[currentMerchant];
        const res = await fetch('/v1/chat_reply', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                category: m2.category,
                merchant: m2.merchant,
                trigger: m2.trigger,
                message: text
            }),
            signal: ctrl2.signal
        });
        clearTimeout(t2);
        const data = await res.json();
        hideTyping();

        if (data.action === 'send') {
            addMsg(data.body, 'vera', false);
        } else if (data.action === 'end') {
            addMsg('Theek hai! Best of luck. Feel free to reach out anytime. 🙂', 'vera', false);
            addSystem('Conversation ended');
            initialized = false;
        } else if (data.action === 'wait') {
            addSystem('Vera is giving you space — she will follow up later.');
        }
    } catch(e) {
        hideTyping();
        if (e.name === 'AbortError') {
            addSystem('Reply timed out — Mistral API slow. Try again.');
        } else {
            addSystem('Error: ' + e.message);
        }
    }
}

function sendQuick(text) {
    document.getElementById('msg-input').value = text;
    sendMsg();
}

function changeMerchant() {
    currentMerchant = document.getElementById('merchant-select').value;
}

// Auto-start on load
window.onload = () => startConversation();
</script>
</body>
</html>"""


@app.route("/v1/chat_message", methods=["POST"])
def chat_message():
    """Single endpoint for the chat UI — handles context + compose in one call."""
    data = request.get_json(force=True)
    category = data.get("category")
    merchant = data.get("merchant") 
    trigger = data.get("trigger")
    customer = data.get("customer")
    
    if not category or not merchant or not trigger:
        return jsonify({"error": "Missing category, merchant, or trigger"}), 400
    
    try:
        result = bot.compose(category, merchant, trigger, customer)
        return jsonify({
            "body": result["body"],
            "cta": result["cta"],
            "send_as": result["send_as"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"],
        })
    except Exception as e:
        logger.error(f"chat_message failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/v1/chat_reply", methods=["POST"])
def chat_reply():
    """Handle reply in chat UI — calls bot.compose with merchant_reply context."""
    data = request.get_json(force=True)
    category = data.get("category")
    merchant = data.get("merchant")
    trigger = data.get("trigger")
    message = data.get("message", "")
    
    if not category or not merchant or not trigger:
        return jsonify({"error": "Missing data"}), 400

    # Detect intent
    msg_lower = message.lower().strip()
    exit_words = ["not interested", "nahi chahiye", "band karo", "stop", "mat bhejo"]
    accept_words = ["yes", "haan", "bilkul", "ok", "sure", "go ahead", "karo", "bhejo", "theek"]
    
    if any(w in msg_lower for w in exit_words):
        return jsonify({"action": "end", "body": "Koi baat nahi! Best of luck. 🙂"})
    
    if any(w in msg_lower for w in accept_words):
        return jsonify({"action": "send", "body": "Bilkul! Main abhi draft karte hoon — 2 minute mein bhejti hoon. ✓"})

    # Generate contextual reply
    try:
        reply_trigger = dict(trigger)
        reply_trigger.setdefault("payload", {})["merchant_reply"] = message
        reply_trigger["kind"] = "active_planning_intent"
        result = bot.compose(category, merchant, reply_trigger, None)
        return jsonify({"action": "send", "body": result["body"]})
    except Exception as e:
        return jsonify({"action": "send", "body": "Samajh gayi! Main check karke aapko update karti hoon."})


@app.route("/demo", methods=["GET"])
def demo():
    return """<!DOCTYPE html>
<html><head><title>Vera Bot — API Demo</title>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:Arial,sans-serif;background:#f5f5f5;color:#1a1a1a}.nav{background:#0f4539;color:white;padding:14px 24px;display:flex;align-items:center;gap:16px}.nav a{color:#7effd4;font-size:13px;text-decoration:none}.nav h1{font-size:16px;font-weight:600;flex:1}.container{max-width:900px;margin:32px auto;padding:0 20px}.card{background:white;border-radius:10px;border:1px solid #e5e7eb;margin-bottom:20px;overflow:hidden}.card-header{padding:14px 20px;display:flex;align-items:center;gap:12px;cursor:pointer;border-bottom:1px solid #f3f4f6}.method{font-size:11px;font-weight:700;padding:3px 10px;border-radius:4px}.get{background:#dcfce7;color:#15803d}.post{background:#dbeafe;color:#1d4ed8}.path{font-weight:600;font-size:14px}.desc{font-size:13px;color:#6b7280;margin-left:auto}.card-body{padding:16px 20px;display:none}.card-body.open{display:block}textarea{width:100%;font-family:monospace;font-size:12px;border:1px solid #e5e7eb;border-radius:6px;padding:10px;resize:vertical;background:#f9fafb}button{background:#0f4539;color:white;border:none;padding:9px 20px;border-radius:6px;cursor:pointer;font-size:13px;margin-top:10px}.response{margin-top:14px;background:#1e1e1e;color:#d4d4d4;border-radius:6px;padding:14px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:300px;overflow-y:auto;display:none}.response.show{display:block}.status-ok{color:#4ade80;font-weight:bold}.status-err{color:#f87171;font-weight:bold}</style>
</head><body>
<div class="nav"><h1>🌿 Vera Bot — API Demo</h1><a href="/">Home</a><a href="/v1/healthz">Health</a><a href="/chat">Chat</a></div>
<div class="container">
<div class="card"><div class="card-header" onclick="toggle('h')"><span class="method get">GET</span><span class="path">/v1/healthz</span><span class="desc">Liveness check</span></div><div class="card-body" id="h"><button onclick="callGet('/v1/healthz','rh')">Send</button><div class="response" id="rh"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('m')"><span class="method get">GET</span><span class="path">/v1/metadata</span><span class="desc">Team info</span></div><div class="card-body" id="m"><button onclick="callGet('/v1/metadata','rm')">Send</button><div class="response" id="rm"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('c')"><span class="method post">POST</span><span class="path">/v1/context</span><span class="desc">Push context</span></div><div class="card-body" id="c"><textarea id="bc" rows="6">{"scope":"merchant","context_id":"m_001","version":1,"payload":{"merchant_id":"m_001","category_slug":"dentists","identity":{"name":"Dr. Meera","owner_first_name":"Meera","city":"Delhi","locality":"Lajpat Nagar","languages":["en","hi"],"verified":true},"performance":{"views":2410,"calls":18,"ctr":0.021,"leads":9,"delta_7d":{"views_pct":0.18,"calls_pct":-0.05,"ctr_pct":0.02}},"offers":[{"title":"Dental Cleaning @ Rs.299","status":"active"}],"signals":["ctr_below_peer_median"],"subscription":{"status":"active","plan":"Pro","days_remaining":82},"customer_aggregate":{"total_unique_ytd":540,"lapsed_180d_plus":78,"retention_6mo_pct":0.38,"high_risk_adult_count":124},"review_themes":[],"conversation_history":[]},"delivered_at":"2026-05-01T10:00:00Z"}</textarea><button onclick="callPost('/v1/context','bc','rc')">Send</button><div class="response" id="rc"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('t')"><span class="method post">POST</span><span class="path">/v1/tick</span><span class="desc">Generate message</span></div><div class="card-body" id="t"><textarea id="bt" rows="3">{"now":"2026-05-01T10:30:00Z","available_triggers":["trg_001"]}</textarea><button onclick="callPost('/v1/tick','bt','rt')">Send</button><div class="response" id="rt"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('r')"><span class="method post">POST</span><span class="path">/v1/reply</span><span class="desc">Handle reply</span></div><div class="card-body" id="r"><textarea id="br" rows="5">{"conversation_id":"conv_001","merchant_id":"m_001","customer_id":null,"from_role":"merchant","message":"Yes please send details","received_at":"2026-05-01T10:45:00Z","turn_number":2}</textarea><button onclick="callPost('/v1/reply','br','rr')">Send</button><div class="response" id="rr"></div></div></div>
</div>
<script>
function toggle(id){document.getElementById(id).classList.toggle('open')}
async function callGet(path,rid){const r=document.getElementById(rid);r.className='response show';r.textContent='Loading...';try{const res=await fetch(path);const d=await res.json();r.innerHTML='<span class="status-ok">HTTP '+res.status+'</span>\n\n'+JSON.stringify(d,null,2)}catch(e){r.innerHTML='<span class="status-err">'+e.message+'</span>'}}
async function callPost(path,bid,rid){const r=document.getElementById(rid);r.className='response show';r.textContent='Loading...';try{const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:document.getElementById(bid).value});const d=await res.json();const c=res.ok?'status-ok':'status-err';r.innerHTML='<span class="'+c+'">HTTP '+res.status+'</span>\n\n'+JSON.stringify(d,null,2)}catch(e){r.innerHTML='<span class="status-err">'+e.message+'</span>'}}
toggle('h');
</script></body></html>"""


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
        "team_members": ["Disha Sikka"],
        "model": "mistral-small-latest",
        "approach": (
            "3-layer architecture: (1) pure-logic decision engine selects intent, CTA shape, "
            "and compulsion levers per trigger kind; (2) context builder assembles grounded "
            "fact block — only verified numbers from the 4 contexts, no hallucination; "
            "(3) Mistral at temperature=0 composes the final message constrained strictly to "
            "the fact block. Auto-reply detection, intent handoff, and graceful exit are "
            "handled as deterministic routing rules, not LLM guesses."
        ),
        "contact_email": "disha@example.com",
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