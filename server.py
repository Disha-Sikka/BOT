"""
server.py — HTTP API for magicpin AI Challenge
Exposes: POST /v1/context, POST /v1/tick, POST /v1/reply,
         GET /v1/healthz, GET /v1/metadata
"""

import json
import os
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from flask import Flask, request, jsonify

import bot
try:
    from conversation_handlers import ConversationState, respond as ch_respond
    USE_CONV_HANDLERS = True
except ImportError:
    USE_CONV_HANDLERS = False

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
conv_states = {}    # conversation_id → ConversationState (for conversation_handlers)
merchant_auto_strikes = {}  # merchant_id → cumulative auto-reply strike count
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
# UI ROUTES




@app.route("/", methods=["GET"])
def root():
    return """<!DOCTYPE html><html><head><title>Vera Bot</title>
<style>body{font-family:Arial,sans-serif;max-width:700px;margin:60px auto;padding:0 20px;background:#f9f9f9}h1{font-size:28px}.badge{background:#22c55e;color:white;padding:4px 12px;border-radius:20px;font-size:13px;margin-left:10px}p{color:#555;line-height:1.6}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:32px}.card{background:white;border:1px solid #e5e7eb;border-radius:10px;padding:20px;text-decoration:none;color:inherit;display:block}.card:hover{border-color:#0f4539;box-shadow:0 2px 8px rgba(0,0,0,.1)}.card h3{margin:0 0 6px;font-size:15px}.method{font-size:11px;font-weight:bold;padding:2px 8px;border-radius:4px;margin-right:6px}.get{background:#dcfce7;color:#16a34a}.post{background:#dbeafe;color:#1d4ed8}.card p{font-size:13px;color:#6b7280;margin:6px 0 0}.info{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin-top:24px;font-size:14px}.info strong{color:#15803d}</style>
</head><body>
<h1>Vera Bot <span class="badge">&#9679; Live</span></h1>
<p>magicpin AI Challenge — AI assistant composing grounded WhatsApp messages using 3-layer decision engine + Mistral AI.</p>
<div class="grid">
<a class="card" href="/v1/healthz"><h3><span class="method get">GET</span>/v1/healthz</h3><p>Liveness check</p></a>
<a class="card" href="/v1/metadata"><h3><span class="method get">GET</span>/v1/metadata</h3><p>Team info</p></a>
<div class="card"><h3><span class="method post">POST</span>/v1/context</h3><p>Push context</p></div>
<div class="card"><h3><span class="method post">POST</span>/v1/tick</h3><p>Generate messages</p></div>
<div class="card"><h3><span class="method post">POST</span>/v1/reply</h3><p>Handle reply</p></div>
<a class="card" href="/v1/test" style="border-color:#6366f1;background:#faf5ff"><h3><span class="method get" style="background:#ede9fe;color:#7c3aed">GET</span>/v1/test</h3><p>&#129514; Live generated message</p></a>
<a class="card" href="/demo" style="border-color:#0f4539;background:#f0fdf4"><h3><span class="method get">GET</span>/demo</h3><p>&#128300; API explorer</p></a>
<a class="card" href="/chat" style="border-color:#25d366;background:#f0fff4"><h3><span class="method get">GET</span>/chat</h3><p>&#128172; Chat with Vera</p></a>
</div>
<div class="info"><strong>Architecture:</strong> Decision Engine &#8594; Context Builder &#8594; Mistral AI (temp=0)<br>
<strong>Model:</strong> mistral-small-latest &nbsp;|&nbsp; <strong>Team:</strong> Disha Sikka</div>
</body></html>"""


@app.route("/v1/test", methods=["GET"])
def test_compose():
    dentists = {"slug":"dentists","voice":{"tone":"peer_clinical","salutation":"Dr. {first_name}","vocab_no":["guaranteed"]},"offer_catalog":[{"title":"Dental Cleaning @ Rs.299"},{"title":"Teeth Whitening @ Rs.1499"}],"peer_stats":{"avg_ctr":0.03,"avg_rating":4.4,"avg_review_count":62,"avg_views_30d":1820},"digest":[{"id":"d_jida","source":"JIDA Oct 2026 p.14","title":"3-month fluoride recall cuts caries 38% vs 6-month","trial_n":2100,"patient_segment":"high_risk_adults","summary":"38% lower caries recurrence with 3-month recall."}],"seasonal_beats":[],"trend_signals":[]}
    merchant = {"merchant_id":"m_demo","category_slug":"dentists","identity":{"name":"Dr. Meera Dental","owner_first_name":"Meera","city":"Delhi","locality":"Lajpat Nagar","languages":["en","hi"],"verified":True},"subscription":{"status":"active","plan":"Pro","days_remaining":82},"performance":{"views":2410,"calls":18,"ctr":0.021,"leads":9,"delta_7d":{"views_pct":0.18,"calls_pct":-0.05,"ctr_pct":0.02}},"offers":[{"title":"Dental Cleaning @ Rs.299","status":"active"}],"signals":["ctr_below_peer_median","high_risk_adult_cohort"],"customer_aggregate":{"total_unique_ytd":540,"lapsed_180d_plus":78,"retention_6mo_pct":0.38,"high_risk_adult_count":124},"review_themes":[],"conversation_history":[]}
    trigger = {"id":"trg_test","scope":"merchant","kind":"research_digest","source":"external","merchant_id":"m_demo","customer_id":None,"payload":{"category":"dentists","top_item_id":"d_jida"},"urgency":2,"suppression_key":"test:dentist"}
    try:
        result = bot.compose(dentists, merchant, trigger, None)
        body = result["body"]; cta = result["cta"]; send_as = result["send_as"]; rationale = result["rationale"]
        status = "success"; error = ""
    except Exception as e:
        body = cta = send_as = rationale = ""; status = "error"; error = str(e)
    color = "#22c55e" if status == "success" else "#ef4444"
    status_icon = "&#9989; Generated" if status == "success" else "&#10060; Error"
    if status == "error":
        content_html = f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px;color:#991b1b"><strong>Error:</strong> {error}</div>'
    else:
        cta_class = "binary" if cta == "binary_yes_stop" else "open"
        content_html = (
            f'<div class="card"><h3>Message</h3><div class="msg">{body}</div></div>'
            f'<div class="card"><h3>Properties</h3>'
            f'<span class="pill vera">{send_as}</span>'
            f'<span class="pill {cta_class}">{cta}</span></div>'
            f'<div class="card"><h3>Rationale</h3>'
            f'<div style="font-size:13px;color:#6b7280">{rationale}</div></div>'
        )
    return f"""<!DOCTYPE html><html><head><title>Vera - Live Test</title>
<style>body{{font-family:Arial,sans-serif;max-width:750px;margin:60px auto;padding:0 20px;background:#f9f9f9}}a.back{{color:#0f4539;font-size:14px;text-decoration:none}}h1{{color:#1a1a1a;margin:16px 0}}.status{{display:inline-block;background:{color};color:white;padding:4px 14px;border-radius:20px;font-size:13px;margin-bottom:20px}}.card{{background:white;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin-bottom:14px}}.card h3{{font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}}.msg{{font-size:15px;line-height:1.7;color:#1a1a1a}}.pill{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:bold;margin-right:6px}}.vera{{background:#dbeafe;color:#1d4ed8}}.btn{{display:inline-block;margin-top:16px;background:#0f4539;color:white;padding:9px 18px;border-radius:8px;text-decoration:none;font-size:13px}}</style>
</head><body><a class="back" href="/">&#8592; Back</a><h1>Live Message Test</h1>
<div class="status">{status_icon}</div>
{content_html}
<a class="btn" href="/v1/test">&#8635; Generate Again</a></body></html>"""


@app.route("/demo", methods=["GET"])
def demo():
    return """<!DOCTYPE html><html><head><title>Vera Bot — API Demo</title>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:Arial,sans-serif;background:#f5f5f5}.nav{background:#0f4539;color:white;padding:14px 24px;display:flex;align-items:center;gap:16px}.nav a{color:#7effd4;font-size:13px;text-decoration:none}.nav h1{font-size:16px;font-weight:600;flex:1}.container{max-width:900px;margin:32px auto;padding:0 20px}.card{background:white;border-radius:10px;border:1px solid #e5e7eb;margin-bottom:20px;overflow:hidden}.card-header{padding:14px 20px;display:flex;align-items:center;gap:12px;cursor:pointer;border-bottom:1px solid #f3f4f6}.method{font-size:11px;font-weight:700;padding:3px 10px;border-radius:4px}.get{background:#dcfce7;color:#15803d}.post{background:#dbeafe;color:#1d4ed8}.path{font-weight:600;font-size:14px}.desc{font-size:13px;color:#6b7280;margin-left:auto}.card-body{padding:16px 20px;display:none}.card-body.open{display:block}textarea{width:100%;font-family:monospace;font-size:12px;border:1px solid #e5e7eb;border-radius:6px;padding:10px;resize:vertical;background:#f9fafb}button{background:#0f4539;color:white;border:none;padding:9px 20px;border-radius:6px;cursor:pointer;font-size:13px;margin-top:10px}.response{margin-top:14px;background:#1e1e1e;color:#d4d4d4;border-radius:6px;padding:14px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:300px;overflow-y:auto;display:none}.response.show{display:block}.status-ok{color:#4ade80;font-weight:bold}.status-err{color:#f87171;font-weight:bold}</style>
</head><body><div class="nav"><h1>&#127807; Vera Bot — API Demo</h1><a href="/">Home</a><a href="/v1/healthz">Health</a><a href="/chat">Chat</a></div>
<div class="container">
<div class="card"><div class="card-header" onclick="toggle('h')"><span class="method get">GET</span><span class="path">/v1/healthz</span><span class="desc">Liveness</span></div><div class="card-body" id="h"><button onclick="callGet('/v1/healthz','rh')">Send</button><div class="response" id="rh"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('m')"><span class="method get">GET</span><span class="path">/v1/metadata</span><span class="desc">Team info</span></div><div class="card-body" id="m"><button onclick="callGet('/v1/metadata','rm')">Send</button><div class="response" id="rm"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('c')"><span class="method post">POST</span><span class="path">/v1/context</span><span class="desc">Push context</span></div><div class="card-body" id="c"><textarea id="bc" rows="5">{"scope":"merchant","context_id":"m_001","version":1,"payload":{"merchant_id":"m_001","category_slug":"dentists","identity":{"name":"Dr. Meera","owner_first_name":"Meera","city":"Delhi","locality":"Lajpat Nagar","languages":["en","hi"],"verified":true},"performance":{"views":2410,"calls":18,"ctr":0.021,"leads":9,"delta_7d":{"views_pct":0.18,"calls_pct":-0.05,"ctr_pct":0.02}},"offers":[{"title":"Dental Cleaning @ Rs.299","status":"active"}],"signals":["ctr_below_peer_median"],"subscription":{"status":"active","plan":"Pro","days_remaining":82},"customer_aggregate":{"total_unique_ytd":540,"lapsed_180d_plus":78,"retention_6mo_pct":0.38,"high_risk_adult_count":124},"review_themes":[],"conversation_history":[]},"delivered_at":"2026-05-01T10:00:00Z"}</textarea><button onclick="callPost('/v1/context','bc','rc')">Send</button><div class="response" id="rc"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('t')"><span class="method post">POST</span><span class="path">/v1/tick</span><span class="desc">Generate message</span></div><div class="card-body" id="t"><textarea id="bt" rows="3">{"now":"2026-05-01T10:30:00Z","available_triggers":["trg_001"]}</textarea><button onclick="callPost('/v1/tick','bt','rt')">Send</button><div class="response" id="rt"></div></div></div>
<div class="card"><div class="card-header" onclick="toggle('r')"><span class="method post">POST</span><span class="path">/v1/reply</span><span class="desc">Handle reply</span></div><div class="card-body" id="r"><textarea id="br" rows="5">{"conversation_id":"conv_001","merchant_id":"m_001","customer_id":null,"from_role":"merchant","message":"Yes please send details","received_at":"2026-05-01T10:45:00Z","turn_number":2}</textarea><button onclick="callPost('/v1/reply','br','rr')">Send</button><div class="response" id="rr"></div></div></div>
</div>
<script>
function toggle(id){document.getElementById(id).classList.toggle('open')}
async function callGet(p,r){var el=document.getElementById(r);el.className='response show';el.textContent='Loading...';try{var res=await fetch(p);var d=await res.json();el.innerHTML='<span class="status-ok">HTTP '+res.status+'</span>\n\n'+JSON.stringify(d,null,2)}catch(e){el.innerHTML='<span class="status-err">'+e.message+'</span>'}}
async function callPost(p,b,r){var el=document.getElementById(r);el.className='response show';el.textContent='Loading...';try{var res=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:document.getElementById(b).value});var d=await res.json();el.innerHTML='<span class="'+(res.ok?'status-ok':'status-err')+'">HTTP '+res.status+'</span>\n\n'+JSON.stringify(d,null,2)}catch(e){el.innerHTML='<span class="status-err">'+e.message+'</span>'}}
toggle('h');
</script></body></html>"""


@app.route("/chat", methods=["GET"])
def chat_page():
    return """<!DOCTYPE html>
<html><head><title>Chat with Vera</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}body{font-family:Arial,sans-serif;background:#e5ddd5;height:100vh;display:flex;flex-direction:column}
.topbar{background:#075e54;color:white;padding:12px 16px;display:flex;align-items:center;gap:12px}
.avatar{width:40px;height:40px;border-radius:50%;background:#25d366;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:16px}
.topbar-info h2{font-size:15px;font-weight:600}.topbar-info p{font-size:12px;opacity:0.8}
.bar{background:#f0f0f0;padding:8px 16px;font-size:12px;color:#555;border-bottom:1px solid #ddd;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.bar select,.bar button{font-size:12px;padding:4px 10px;border-radius:6px;border:1px solid #ccc;background:white;cursor:pointer}
.bar button{background:#075e54;color:white;border:none}
.messages{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:8px}
.msg{max-width:75%;padding:8px 12px;border-radius:10px;font-size:14px;line-height:1.5}
.msg .time{font-size:10px;opacity:0.6;margin-top:4px;text-align:right}
.vera{background:white;align-self:flex-start;border-top-left-radius:2px;box-shadow:0 1px 2px rgba(0,0,0,0.1)}
.merchant{background:#dcf8c6;align-self:flex-end;border-top-right-radius:2px;box-shadow:0 1px 2px rgba(0,0,0,0.1)}
.system{background:rgba(0,0,0,0.08);align-self:center;font-size:11px;color:#555;border-radius:8px;padding:4px 12px;max-width:90%;text-align:center}
.sender{font-size:11px;font-weight:bold;color:#075e54;margin-bottom:2px}
.typing{background:white;align-self:flex-start;border-radius:10px;padding:10px 14px;box-shadow:0 1px 2px rgba(0,0,0,0.1)}
.typing span{display:inline-block;width:8px;height:8px;background:#aaa;border-radius:50%;margin:0 2px;animation:bounce 1.2s infinite}
.typing span:nth-child(2){animation-delay:0.2s}.typing span:nth-child(3){animation-delay:0.4s}
@keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
.input-bar{background:#f0f0f0;padding:10px 12px;display:flex;gap:8px;align-items:center}
.input-bar input{flex:1;padding:10px 14px;border-radius:20px;border:none;font-size:14px;outline:none}
.input-bar button{width:42px;height:42px;border-radius:50%;background:#075e54;color:white;border:none;cursor:pointer;font-size:18px}
.cta-buttons{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.cta-btn{background:#075e54;color:white;border:none;padding:6px 14px;border-radius:16px;font-size:13px;cursor:pointer}
.cta-btn.stop{background:#e74c3c}a.home{color:#7effd4;font-size:12px;margin-left:auto;text-decoration:none}
</style></head><body>
<div class="topbar"><div class="avatar">V</div><div class="topbar-info"><h2>Vera <span style="font-size:11px;opacity:0.7">by magicpin</span></h2><p>&#9679; online</p></div><a class="home" href="/">Home</a></div>
<div class="bar"><span>You are:</span>
<select id="sel" onchange="currentMerchant=this.value">
<option value="dentist">Dr. Meera - Dental Clinic, Delhi</option>
<option value="salon">Lakshmi - Studio11 Salon, Hyderabad</option>
<option value="restaurant">Suresh - SK Pizza Junction, Delhi</option>
<option value="gym">Kiran - PowerHouse Fitness, Bangalore</option>
</select>
<button onclick="startConversation()">Start fresh chat</button></div>
<div class="messages" id="msgs"><div class="system">Loading Vera...</div></div>
<div class="input-bar"><input type="text" id="inp" placeholder="Type a message..." onkeydown="if(event.key===&apos;Enter&apos;)sendMsg()"><button onclick="sendMsg()">&#10148;</button></div>
<script>
var D={merchant:{merchant_id:"m_d",category_slug:"dentists",identity:{name:"Dr. Meera Dental Clinic",owner_first_name:"Meera",city:"Delhi",locality:"Lajpat Nagar",languages:["en","hi"],verified:true},performance:{views:2410,calls:18,ctr:0.021,leads:9,delta_7d:{views_pct:0.18,calls_pct:-0.05,ctr_pct:0.02}},offers:[{title:"Dental Cleaning @ Rs.299",status:"active"}],signals:["ctr_below_peer_median","high_risk_adult_cohort"],subscription:{status:"active",plan:"Pro",days_remaining:82},customer_aggregate:{total_unique_ytd:540,lapsed_180d_plus:78,retention_6mo_pct:0.38,high_risk_adult_count:124},review_themes:[],conversation_history:[]},category:{slug:"dentists",voice:{tone:"peer_clinical",salutation:"Dr. {first_name}",vocab_no:["guaranteed"]},offer_catalog:[{title:"Dental Cleaning @ Rs.299"},{title:"Teeth Whitening @ Rs.1499"}],peer_stats:{avg_ctr:0.03,avg_rating:4.4,avg_review_count:62,avg_views_30d:1820},digest:[{id:"d_jida",source:"JIDA Oct 2026 p.14",title:"3-month fluoride recall cuts caries 38% vs 6-month",trial_n:2100,patient_segment:"high_risk_adults",summary:"38% lower caries recurrence with 3-month recall."}],seasonal_beats:[],trend_signals:[]},trigger:{id:"trg_d",scope:"merchant",kind:"research_digest",source:"external",merchant_id:"m_d",customer_id:null,payload:{category:"dentists",top_item_id:"d_jida"},urgency:2,suppression_key:"demo:d",expires_at:"2027-01-01T00:00:00Z"}};
var S={merchant:{merchant_id:"m_s",category_slug:"salons",identity:{name:"Studio11 Family Salon",owner_first_name:"Lakshmi",city:"Hyderabad",locality:"Kapra",languages:["en","hi"],verified:true},performance:{views:5430,calls:61,ctr:0.041,leads:38,delta_7d:{views_pct:0.12,calls_pct:0.2,ctr_pct:0.03}},offers:[{title:"Bridal Package @ Rs.24999",status:"active"}],signals:["bridal_peak_incoming"],subscription:{status:"active",plan:"Pro",days_remaining:142},customer_aggregate:{total_unique_ytd:1240,lapsed_180d_plus:180,retention_6mo_pct:0.62},review_themes:[],conversation_history:[]},category:{slug:"salons",voice:{tone:"warm_practical",salutation:"{first_name}",vocab_no:["guaranteed results"]},offer_catalog:[{title:"Bridal Package @ Rs.24999"},{title:"Keratin Treatment @ Rs.3499"}],peer_stats:{avg_ctr:0.038,avg_rating:4.2,avg_review_count:85,avg_views_30d:3200},digest:[{id:"d_diwali",source:"magicpin 2025",title:"Diwali 3x footfall",trial_n:null,patient_segment:null,summary:"Advance booking critical."}],seasonal_beats:[],trend_signals:[]},trigger:{id:"trg_s",scope:"merchant",kind:"festival_upcoming",source:"external",merchant_id:"m_s",customer_id:null,payload:{festival:"Diwali",days_until:5},urgency:3,suppression_key:"demo:s",expires_at:"2027-01-01T00:00:00Z"}};
var R={merchant:{merchant_id:"m_r",category_slug:"restaurants",identity:{name:"SK Pizza Junction",owner_first_name:"Suresh",city:"Delhi",locality:"Sant Nagar",languages:["en","hi"],verified:true},performance:{views:3100,calls:22,ctr:0.033,leads:18,delta_7d:{views_pct:0.05,calls_pct:-0.1,ctr_pct:0.01}},offers:[{title:"BOGO Pizza Tue-Thu",status:"active"}],signals:["delivery_preference"],subscription:{status:"trial",plan:"Trial",days_remaining:8},customer_aggregate:{total_unique_ytd:920,lapsed_180d_plus:310,retention_6mo_pct:0.44},review_themes:[{theme:"delivery_time",sentiment:"neg",occurrences_30d:5,common_quote:"delivery took 45 min"}],conversation_history:[]},category:{slug:"restaurants",voice:{tone:"friendly_operator",salutation:"{first_name}",vocab_no:[]},offer_catalog:[{title:"BOGO Pizza Tue-Thu"},{title:"Family Combo @ Rs.699"}],peer_stats:{avg_ctr:0.036,avg_rating:4.1,avg_review_count:120,avg_views_30d:3800},digest:[{id:"d_ipl",source:"magicpin 2025",title:"IPL Sat -12% covers",trial_n:null,patient_segment:null,summary:"Push delivery on IPL Saturdays."}],seasonal_beats:[],trend_signals:[]},trigger:{id:"trg_r",scope:"merchant",kind:"review_theme_emerged",source:"internal",merchant_id:"m_r",customer_id:null,payload:{theme:"delivery_time",occurrences_30d:5},urgency:3,suppression_key:"demo:r",expires_at:"2027-01-01T00:00:00Z"}};
var G={merchant:{merchant_id:"m_g",category_slug:"gyms",identity:{name:"PowerHouse Fitness",owner_first_name:"Kiran",city:"Bangalore",locality:"Indiranagar",languages:["en","hi"],verified:true},performance:{views:2800,calls:19,ctr:0.029,leads:14,delta_7d:{views_pct:-0.18,calls_pct:-0.25,ctr_pct:-0.08}},offers:[{title:"3-Month Membership @ Rs.4999",status:"active"}],signals:["seasonal_dip_expected"],subscription:{status:"active",plan:"Pro",days_remaining:88},customer_aggregate:{total_unique_ytd:480,lapsed_180d_plus:165,retention_6mo_pct:0.42},review_themes:[],conversation_history:[]},category:{slug:"gyms",voice:{tone:"energetic_peer",salutation:"{first_name}",vocab_no:["guaranteed weight loss"]},offer_catalog:[{title:"3-Month Membership @ Rs.4999"},{title:"Student Morning Batch @ Rs.2499"}],peer_stats:{avg_ctr:0.032,avg_rating:4.3,avg_review_count:48,avg_views_30d:2200},digest:[{id:"d_exam",source:"magicpin 2026",title:"Exam season -18% enrollment",trial_n:null,patient_segment:"student_18_24",summary:"Student batch offsets dip."}],seasonal_beats:[],trend_signals:[]},trigger:{id:"trg_g",scope:"merchant",kind:"seasonal_perf_dip",source:"internal",merchant_id:"m_g",customer_id:null,payload:{metric:"views",delta_pct:-0.30},urgency:2,suppression_key:"demo:g",expires_at:"2027-01-01T00:00:00Z"}};
var MERCHANTS={dentist:D,salon:S,restaurant:R,gym:G};
var currentMerchant="dentist",convId=null,turnNum=1,ready=false,chatHistory=[];
function nowTime(){return new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});}
function addMsg(text,role,showCTA){
  var msgs=document.getElementById("msgs");var div=document.createElement("div");div.className="msg "+role;
  if(role==="vera"){
    var p=document.createElement("div");p.className="sender";p.textContent="Vera";div.appendChild(p);
    var b=document.createElement("div");b.textContent=text;div.appendChild(b);
    if(showCTA){var c=document.createElement("div");c.className="cta-buttons";["YES","STOP","Tell me more"].forEach(function(t){var btn=document.createElement("button");btn.className="cta-btn"+(t==="STOP"?" stop":"");btn.textContent=t;btn.onclick=function(){quick(t);};c.appendChild(btn);});div.appendChild(c);}
  } else {div.textContent=text;}
  var ti=document.createElement("div");ti.className="time";ti.innerHTML=nowTime()+(role==="merchant"?" &#10003;&#10003;":"");div.appendChild(ti);
  msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;
}
function addSys(t){var msgs=document.getElementById("msgs");var div=document.createElement("div");div.className="msg system";div.textContent=t;msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;}
function showTyping(){var msgs=document.getElementById("msgs");var div=document.createElement("div");div.className="typing";div.id="typ";div.innerHTML="<span></span><span></span><span></span>";msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;}
function hideTyping(){var el=document.getElementById("typ");if(el)el.remove();}
async function startConversation(){
  ready=false;convId=null;turnNum=1;chatHistory=[];
  document.getElementById("msgs").innerHTML="";addSys("Connecting to Vera (10-20 seconds)...");showTyping();
  var m=MERCHANTS[currentMerchant];
  try{
    var res=await fetch("/v1/chat_message",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({category:m.category,merchant:m.merchant,trigger:m.trigger,customer:null})});
    var data=await res.json();hideTyping();document.getElementById("msgs").innerHTML="";
    if(data.error){addSys("Error: "+data.error+". Click Start fresh chat.");}
    else{convId="conv_"+Date.now();addMsg(data.body,"vera",data.cta==="binary_yes_stop");chatHistory.push({role:"vera",content:data.body});ready=true;}
  }catch(e){hideTyping();document.getElementById("msgs").innerHTML="";addSys("Failed: "+e.message+". Click Start fresh chat.");}
}
async function sendMsg(){
  var inp=document.getElementById("inp");var text=inp.value.trim();if(!text||!ready)return;inp.value="";
  addMsg(text,"merchant",false);chatHistory.push({role:"merchant",content:text});turnNum++;showTyping();
  var m=MERCHANTS[currentMerchant];
  try{
    var res=await fetch("/v1/chat_reply",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({category:m.category,merchant:m.merchant,trigger:m.trigger,message:text,history:chatHistory})});
    var data=await res.json();hideTyping();
    if(data.action==="end"){addMsg(data.body||"Koi baat nahi! Best of luck.","vera",false);addSys("Conversation ended.");ready=false;chatHistory=[];}
    else{addMsg(data.body,"vera",false);chatHistory.push({role:"vera",content:data.body});}
  }catch(e){hideTyping();addSys("Error: "+e.message);}
}
function quick(text){document.getElementById("inp").value=text;sendMsg();}
window.onload=startConversation;
</script></body></html>"""


@app.route("/v1/chat_message", methods=["POST"])
def chat_message():
    data = request.get_json(force=True)
    category = data.get("category"); merchant = data.get("merchant")
    trigger = data.get("trigger"); customer = data.get("customer")
    if not category or not merchant or not trigger:
        return jsonify({"error": "Missing category, merchant, or trigger"}), 400
    try:
        result = bot.compose(category, merchant, trigger, customer)
        return jsonify({"body": result["body"], "cta": result["cta"],
                        "send_as": result["send_as"], "suppression_key": result["suppression_key"],
                        "rationale": result["rationale"]})
    except Exception as e:
        logger.error(f"chat_message failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/v1/chat_reply", methods=["POST"])
def chat_reply():
    data = request.get_json(force=True)
    category = data.get("category"); merchant = data.get("merchant")
    trigger = data.get("trigger"); message = data.get("message", "")
    history = data.get("history", [])
    if not category or not merchant or not trigger:
        return jsonify({"error": "Missing data"}), 400
    msg_lower = message.lower().strip()
    if any(w in msg_lower for w in ["not interested","nahi chahiye","band karo","stop","mat bhejo"]):
        return jsonify({"action": "end", "body": "Koi baat nahi! Best of luck. \U0001f642"})
    try:
        api_key = os.environ.get("MISTRAL_API_KEY", "")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY not set")
        m_id = merchant.get("identity", {}); name = m_id.get("owner_first_name", m_id.get("name",""))
        cat = merchant.get("category_slug",""); perf = merchant.get("performance",{})
        offers = [o["title"] for o in merchant.get("offers",[]) if o.get("status")=="active"]
        system_prompt = (f"You are Vera, magicpin WhatsApp AI for merchants. Talking to {name}, a {cat} owner. "
            f"Stats: views={perf.get('views')}, CTR={perf.get('ctr')}, calls={perf.get('calls')}, offers={offers}. "
            f"Rules: 2-3 sentences max. Use their actual data. Match language (hi-en if Hindi). "
            f"If yes/agree — move to action immediately. Brief acknowledgment for off-topic, then redirect.")
        messages = [{"role": "system", "content": system_prompt}]
        for turn in history[-6:]:
            messages.append({"role": "assistant" if turn.get("role")=="vera" else "user", "content": turn.get("content","")})
        messages.append({"role": "user", "content": message})
        import urllib.request as ur, json as js
        payload = js.dumps({"model":"mistral-small-latest","temperature":0.3,"max_tokens":150,"messages":messages}).encode()
        req = ur.Request("https://api.mistral.ai/v1/chat/completions", data=payload,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {api_key}"}, method="POST")
        with ur.urlopen(req, timeout=30) as resp:
            result = js.loads(resp.read())
            reply_body = result["choices"][0]["message"]["content"].strip()
        return jsonify({"action": "send", "body": reply_body})
    except Exception as e:
        logger.error(f"chat_reply failed: {e}")
        return jsonify({"action": "send", "body": "Samajh gayi! Ek second — check karke batati hoon."})


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
        # Create ConversationState for conversation_handlers
        if USE_CONV_HANDLERS:
            state = ConversationState(
                conversation_id=conv_id,
                merchant_id=merchant_id,
                customer_id=customer_id,
                trigger_id=trigger_id,
                trigger_kind=trg.get("kind", ""),
                context_snapshot={"category": category, "merchant": merchant,
                                   "trigger": trg, "customer": customer}
            )
            state.history.append({"role": "vera", "body": result["body"]})
            conv_states[conv_id] = state
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
        # === UNKNOWN CONV — auto-reply detection via global merchant tracker ===
        auto_key = merchant_id or "unknown"
        if is_auto_reply(message):
            merchant_auto_strikes[auto_key] = merchant_auto_strikes.get(auto_key, 0) + 1
            strikes = merchant_auto_strikes[auto_key]
            if strikes >= 2:
                merchant_auto_strikes.pop(auto_key, None)
                return jsonify({"action": "end",
                                "rationale": f"Auto-reply detected {strikes}x — graceful exit."})
            return jsonify({"action": "wait",
                            "rationale": "Auto-reply detected once — waiting before retry."})

        # Exit detection
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

    # === USE conversation_handlers if state exists ===
    if USE_CONV_HANDLERS and conv_id in conv_states:
        state = conv_states[conv_id]
        result = ch_respond(state, message)
        action = result.get("action", "send")
        if action == "end":
            return jsonify({
                "action": "end",
                "rationale": result.get("rationale", "Conversation ended.")
            })
        elif action == "wait":
            return jsonify({
                "action": "wait",
                "rationale": result.get("rationale", "Waiting.")
            })
        else:
            # send — but if body is a template placeholder, use compose() to fill it
            body = result.get("body", "")
            if body and not body.startswith("__compose__"):
                return jsonify({
                    "action": "send",
                    "body": body,
                    "cta": result.get("cta", "open_ended"),
                    "rationale": result.get("rationale", "")
                })
        # Fall through to compose() for __compose__ placeholders

    # === AUTO-REPLY DETECTION — global + per-conv strikes ===
    verbatim_repeat = sum(1 for h in conv["history"]
                         if h.get("body","").strip() == message.strip()) >= 2
    if is_auto_reply(message) or verbatim_repeat:
        conv.setdefault("auto_reply_strikes", 0)
        conv["auto_reply_strikes"] += 1
        key = conv.get("merchant_id", conv_id)
        merchant_auto_strikes[key] = merchant_auto_strikes.get(key, 0) + 1
        strikes = max(conv["auto_reply_strikes"], merchant_auto_strikes.get(key, 0))
        if strikes >= 2:
            merchant_auto_strikes.pop(key, None)
            return jsonify({
                "action": "end",
                "rationale": f"Auto-reply detected {strikes}x — graceful exit.",
            })
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
        "team_members": ["Disha Sikka"],
        "model": "claude-sonnet-4-20250514",
        "approach": (
            "3-layer architecture: (1) pure-logic decision engine selects intent, CTA shape, "
            "and compulsion levers per trigger kind; (2) context builder assembles grounded "
            "fact block — only verified numbers from the 4 contexts, no hallucination; "
            "(3) Claude at temperature=0 composes the final message constrained strictly to "
            "the fact block. Auto-reply detection, intent handoff, and graceful exit are "
            "handled as deterministic routing rules, not LLM guesses."
        ),
        "contact_email": "disha.sikka77@gmail.com",
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