# Vera Bot — magicpin AI Challenge Submission

**Team**: Solo  
**Model**: `mistral-small-latest` at `temperature=0`  
**Approach**: 3-layer Decision Engine + Context Builder + LLM Composer

---

## Architecture

```
                    ┌─────────────────────────────┐
 4 context inputs → │  Layer 1: Decision Engine    │ → intent, CTA shape, compulsion levers
                    │  (pure Python, no LLM)       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Layer 2: Context Builder    │ → grounded facts block
                    │  (assembles verifiable data) │   (only what's in contexts)
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Layer 3: Mistral (temp=0)   │ → final WhatsApp body
                    │  constrained to fact block   │
                    └─────────────────────────────┘
```

### Layer 1 — Decision Engine (no LLM)

Every trigger kind maps to:
- **CTA shape**: `binary_yes_stop` or `open_ended` — determined by trigger semantics, not LLM guess
- **Compulsion levers**: 3 levers per trigger kind from the 8 in the brief (specificity, loss-aversion, social-proof, curiosity, reciprocity, effort-externalization, asking-the-merchant, single-binary)
- **send_as**: `vera` or `merchant_on_behalf` — from trigger scope
- **Peer gap signal**: CTR vs peer median, computed before prompt
- **Relevant digest items**: matched to trigger payload's `top_item_id` first

### Layer 2 — Context Builder

Produces a structured facts block with exactly the information the LLM is allowed to use:
- Category voice rules, taboo words, offer catalog, peer stats, digest items
- Merchant: name/salutation, performance numbers, active offers, signals, customer aggregate, conversation history, review themes
- Trigger: kind, payload, urgency
- Customer (if present): name, language pref, state, visit history, slot preferences
- Explicit DECISION block: send_as, cta, levers — LLM is told what to do, not asked to figure it out

### Layer 3 — LLM Composer

Claude at temperature=0 receives:
1. Category-specific system prompt with voice rules and taboos
2. The grounded fact block (no hallucination possible — all numbers come from context)
3. Instruction to anchor on ≥1 verifiable fact and use the specified levers

The LLM's job is to *write*, not to *decide*. All routing logic is in Layers 1-2.

---

## Key design choices

### Decision quality over writing quality

Per the judge's stated criteria: *"We score decisions, not writing style."*

- Trigger-to-CTA mapping is explicit lookup, not prompted
- Compulsion lever selection is explicit lookup, not prompted
- `send_as` is derived from trigger scope (zero ambiguity)
- Language detection is per-merchant identity, enforced in prompt

### Specificity by construction

Every prompt includes:
- Exact CTR numbers (merchant vs peer median, gap computed)
- Digest item with source, trial size, patient segment
- Active offer titles from merchant's catalog (never catalog defaults if merchant has their own)
- Customer-specific data (last visit date, visit count, slot prefs) when customer-facing

### No hallucination architecture

The context builder explicitly lists what facts ARE available and instructs the LLM: *"DO NOT fabricate anything not in the context above."* The system prompt reinforces this as rule #1.

### Determinism

- `temperature=0` throughout
- Same 4-context inputs → same output (verified)
- Suppression keys prevent duplicate sends

---

## Multi-turn handling (`conversation_handlers.py`)

| Signal | Detection | Action |
|---|---|---|
| Auto-reply (pattern) | Regex on 20+ known canned phrases | 1 redirect attempt, then graceful exit |
| Verbatim repeat (≥3) | Exact string match in history | Confirmed auto-reply → exit |
| Exit ("not interested", "stop", etc.) | Regex | Immediate graceful exit with positive note |
| Accept ("yes", "haan", "bilkul", etc.) | Regex | **Immediate action** — zero re-qualification |
| Question | "?" or question words | Direct answer with merchant's own numbers |
| Language switch | Per-turn detection (Devanagari + Latin) | Response matches detected language |

**The key anti-pattern we avoid**: When a merchant says "yes/I want to join", we do NOT loop back to qualifying questions. We route to action immediately.

---

## HTTP API

| Endpoint | Description |
|---|---|
| `POST /v1/context` | Idempotent context push, version-controlled |
| `POST /v1/tick` | Evaluates active triggers, fires proactive messages |
| `POST /v1/reply` | Full reply handler with auto-reply detection + intent routing |
| `GET /v1/healthz` | Liveness probe with context counts |
| `GET /v1/metadata` | Team + approach metadata |

Run: `python server.py [port]` (default 8080)  
Requires: `MISTRAL_API_KEY` env var, `pip install flask`

---

## Tradeoffs

1. **LLM call per message**: adds ~2-4s latency but gives natural, context-sensitive copy. Retrieval-augmented with the category digest embedded would be better at scale.

2. **In-memory state**: fine for the test window; production would use Redis or a DB.

3. **Trigger routing is lookup-based**: very robust for the 15+ known trigger kinds; new kinds get a reasonable fallback (`open_ended` CTA, `[specificity, curiosity]` levers) but won't be as sharp as the mapped ones.

4. **No slot management**: customer-facing recall messages reference "weekday evening" preference but don't book real slots (not in scope of the challenge dataset).

---

## What additional context would have helped most

1. **Real merchant reply corpus** — knowing how merchants actually respond to each trigger kind would let us tune the multi-turn state machine much more precisely (e.g., typical follow-up question types by category).

2. **Historical suppression data** — knowing which messages a merchant has already received prevents tonal repetition across sessions (we avoid within-session repeats but not cross-session).

3. **Verified slot availability** — for customer-facing recall/booking triggers, real open slots would make the message dramatically more actionable than "let me know a time that works."

4. **Review sentiment at item level** — the `review_themes` array is powerful but loses fidelity vs. actual review text. Full reviews would let us anchor on merchant-specific quotes ("3 reviewers mentioned 30-min Sunday waits").