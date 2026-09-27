# MagicPin Vera AI Challenge — Implementation Plan

## 1. What We Are Actually Building

### The Challenge in Simple Terms

We are building an **HTTP API server** that acts as the messaging brain behind **Vera**, magicpin's AI merchant assistant. Our server receives structured context about merchants, their customers, and events — then composes high-quality, personalized WhatsApp messages.

### What Vera Represents

Vera is magicpin's AI assistant that talks to ~6,000-10,000 merchants daily over WhatsApp. It helps them improve Google Business Profiles, run campaigns, respond to customers, and make data-driven decisions. We are rebuilding Vera's **composition engine** — the part that decides *what to say* and *how to say it*.

### Component Responsibilities

| Component | Who Owns It | What It Does |
|---|---|---|
| **Our Application** | Us | HTTP server exposing 5 endpoints. Receives context, stores state, decides what messages to send, composes messages, handles multi-turn conversations. |
| **The LLM** | Us (API call) | We call a commercial LLM (OpenAI/Anthropic/Google/etc.) to generate message text. Our decision engine decides *what* to say; the LLM crafts *how* to say it. |
| **The Evaluator/Judge** | MagicPin | An automated harness that pushes context to our server, calls `/v1/tick` to trigger message composition, plays the merchant role in conversations via `/v1/reply`, and scores our output across 5 dimensions using an LLM scorer. |
| **The Dataset** | MagicPin (shared) | 5 categories, 50 merchants, 200 customers, 100 triggers — deterministically generated from seed files. Everyone gets the same data. |
| **The Simulator** | MagicPin (provided) | `judge_simulator.py` — a local testing tool that runs mini scenarios against our endpoint. Uses an LLM to score our messages on 5 dimensions (0-10 each, 50 total). |

### Key Distinction

The judge pushes context → we store it. The judge calls tick → we decide what to send. The judge plays merchant → we handle the reply. **We never call the judge.** All communication is judge-initiated HTTP calls to our server.

---

## 2. Exact API Contract

### 2.1 `GET /v1/healthz` — Liveness Probe

**Purpose**: Judge checks if our server is alive. Polled every 60s during test. 3 consecutive failures = disqualification.

**Request**: `GET /v1/healthz` — no body.

**Response (200)**:
```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "contexts_loaded": {
    "category": 5,
    "merchant": 50,
    "customer": 200,
    "trigger": 0
  }
}
```

**Required fields**: `status`, `uptime_seconds`, `contexts_loaded` (with all 4 scope counts).

**Validation**: `contexts_loaded` must reflect actual stored context counts. After warmup, must show 5 categories + 50 merchants + 200 customers. Mismatch = warmup failure.

**Latency budget**: 2s. Judge retries 3x.

---

### 2.2 `GET /v1/metadata` — Bot Identity

**Purpose**: Reports team info and approach. Called once at start.

**Request**: `GET /v1/metadata` — no body.

**Response (200)**:
```json
{
  "team_name": "Team Name",
  "team_members": ["Member1"],
  "model": "gpt-4o",
  "approach": "hybrid rule-based decision engine + LLM composer",
  "contact_email": "email@example.com",
  "version": "1.0.0",
  "submitted_at": "2026-09-26T18:00:00Z"
}
```

**Required fields**: `team_name`, `model`, `version`.

**Latency budget**: 2s. No retry.

---

### 2.3 `POST /v1/context` — Receive Context Push

**Purpose**: Judge pushes category, merchant, customer, or trigger data. This is how our bot learns about the world.

**Request body**:
```json
{
  "scope": "category" | "merchant" | "customer" | "trigger",
  "context_id": "dentists",
  "version": 1,
  "payload": { /* full context object */ },
  "delivered_at": "2026-04-26T10:00:00Z"
}
```

**Required fields**: `scope`, `context_id`, `version`, `payload`, `delivered_at`.

**Behavior rules**:
1. **Idempotent** by `(context_id, version)`. Re-posting same version = no-op, return 409.
2. Higher `version` for same `context_id` **replaces** prior version **atomically**.
3. Lower `version` than current = stale, return 409.
4. Must persist until test ends (in-memory OK).

**Response (200)** — accepted:
```json
{
  "accepted": true,
  "ack_id": "ack_dentists_v1",
  "stored_at": "2026-04-26T10:00:00.123Z"
}
```

**Response (409)** — version conflict (same or older version):
```json
{
  "accepted": false,
  "reason": "stale_version",
  "current_version": 1
}
```

**Response (400)** — malformed:
```json
{
  "accepted": false,
  "reason": "invalid_scope",
  "details": "scope must be one of: category, merchant, customer, trigger"
}
```

**Latency budget**: 5s. No retry. Payload size cap: 500 KB.

---

### 2.4 `POST /v1/tick` — Periodic Wake-Up

**Purpose**: Judge advances simulated time and asks our bot if it wants to send any proactive messages. Called every 5 simulated minutes.

**Request body**:
```json
{
  "now": "2026-04-26T10:30:00Z",
  "available_triggers": ["trg_001_research_digest_dentists", "trg_003_recall_due_priya"]
}
```

**Required fields**: `now`, `available_triggers` (list of trigger context_ids currently active).

**Response (200)** — bot sends message(s):
```json
{
  "actions": [
    {
      "conversation_id": "conv_m001_research_W17",
      "merchant_id": "m_001_drmeera_dentist_delhi",
      "customer_id": null,
      "send_as": "vera",
      "trigger_id": "trg_001_research_digest_dentists",
      "template_name": "vera_research_digest_v1",
      "template_params": ["Dr. Meera", "...", "..."],
      "body": "Dr. Meera, JIDA's Oct issue landed...",
      "cta": "open_ended",
      "suppression_key": "research:dentists:2026-W17",
      "rationale": "External research digest with merchant-relevant clinical anchor"
    }
  ]
}
```

**Response (200)** — bot decides not to send:
```json
{ "actions": [] }
```

**Required fields per action**: `conversation_id`, `merchant_id`, `send_as`, `trigger_id`, `body`, `cta`, `suppression_key`, `rationale`.

**Optional fields**: `customer_id` (null for merchant-facing), `template_name`, `template_params`.

**Validation rules**:
- `conversation_id` must be unique (new conversation). Reusing existing = invalid.
- `send_as`: `"vera"` (merchant-facing) or `"merchant_on_behalf"` (customer-facing).
- `cta`: `"open_ended"`, `"binary_yes_no"`, `"binary_confirm_cancel"`, `"multi_choice_slot"`, `"none"`.
- Missing required fields → action scored as 0 with -2 penalty.
- Max 20 actions per tick.
- URLs in body → hard fail, -3 penalty per URL.

**Latency budget**: 10s (simulator), 30s (real judge). No retry.

---

### 2.5 `POST /v1/reply` — Receive Merchant/Customer Reply

**Purpose**: Judge plays merchant/customer replying to our previous message. We must respond synchronously.

**Request body**:
```json
{
  "conversation_id": "conv_m001_research_W17",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Yes please send the abstract",
  "received_at": "2026-04-26T10:45:00Z",
  "turn_number": 2
}
```

**Required fields**: `conversation_id`, `from_role`, `message`, `received_at`, `turn_number`.

**Response (200)** — three valid `action` values:

**Send:**
```json
{
  "action": "send",
  "body": "Sending the abstract now...",
  "cta": "binary_yes_no",
  "rationale": "Honoring merchant's accept; providing next step"
}
```

**Wait:**
```json
{
  "action": "wait",
  "wait_seconds": 14400,
  "rationale": "Detected auto-reply; backing off 4 hours"
}
```

**End:**
```json
{
  "action": "end",
  "rationale": "Merchant explicitly opted out; closing conversation"
}
```

**Validation rules**:
- `action` must be `"send"`, `"wait"`, or `"end"`.
- `send` requires `body` (non-empty) + `rationale`.
- `wait` requires `wait_seconds` + `rationale`.
- `end` requires `rationale`.
- Same `body` verbatim as previous send in same conversation → -2 anti-repetition penalty.

**Latency budget**: 10s (simulator), 30s (real judge). Timeout = `bot_silent`.

---

## 3. Simulation Flow

### Phase 1 — Warmup (T-15 min)

```
Judge                                    Our Bot
  │                                        │
  │──── GET /v1/healthz ──────────────────►│ → {"status":"ok", "contexts_loaded":{all 0}}
  │──── GET /v1/metadata ─────────────────►│ → team info
  │                                        │
  │ Loop: push 5 categories                │
  │──── POST /v1/context (category) ──────►│ → {"accepted":true}
  │                                        │
  │ Loop: push 50 merchants                │
  │──── POST /v1/context (merchant) ──────►│ → {"accepted":true}
  │                                        │
  │ Loop: push 200 customers               │
  │──── POST /v1/context (customer) ──────►│ → {"accepted":true}
  │                                        │
  │ Wait 60s                               │
  │──── GET /v1/healthz ──────────────────►│ → {"contexts_loaded":{"category":5,"merchant":50,"customer":200,"trigger":0}}
  │                                        │
  │ ✓ Warmup passed                        │
```

### Phase 2 — Test Window (60 simulated minutes, ~12 ticks)

Each tick cycle:

```
Judge                                    Our Bot
  │                                        │
  │ Push new/updated contexts              │
  │──── POST /v1/context (trigger) ───────►│ → {"accepted":true}
  │──── POST /v1/context (category v2) ───►│ → {"accepted":true}  (mid-test injection)
  │                                        │
  │ Tick                                   │
  │──── POST /v1/tick ────────────────────►│
  │     {now, available_triggers}          │
  │◄─── {"actions": [{...}]} ─────────────│ ← Bot decides what to send
  │                                        │
  │ For each action, judge plays merchant  │
  │──── POST /v1/reply ───────────────────►│
  │     {conversation_id, message}         │
  │◄─── {"action":"send","body":"..."} ───│ ← Bot responds
  │                                        │
  │ Up to 5 turns per conversation         │
  │──── POST /v1/reply (turn 3) ──────────►│ → response
  │──── POST /v1/reply (turn 4) ──────────►│ → response
  │──── POST /v1/reply (turn 5) ──────────►│ → {"action":"end"}
```

### Phase 3 — Adaptive Context Injection (interleaved with Phase 2)

Between ticks, judge injects:
- New `digest` items (5 per category, as version bumps)
- Updated `performance` (10 merchants get new numbers)
- New triggers (15 new triggers)
- For 5 merchants: new `customer` context + `recall_due` trigger 2 minutes later

**Key**: Our bot must use the LATEST version of any context. Old data = low score. Hallucinated data = penalty.

### Phase 4 — Replay Test (top 10 only)

Three standalone scenarios:

1. **Auto-reply hell**: Same canned auto-reply 4 times. Bot must detect → acknowledge once → wait → end.
2. **Intent transition**: Merchant says "ok let's do it". Bot must switch from qualifying to action mode.
3. **Hostile/off-topic**: Merchant hostile or asks off-topic question. Bot must exit gracefully or redirect politely.

### Suppression Behavior

- Each action has a `suppression_key`.
- Once an action is sent with a given suppression key, the bot should NOT send another action with the same key.
- Conversation ended by merchant hostility → suppress all triggers for that merchant.

### Version Handling

- Context `version` is monotonically increasing per `context_id`.
- Higher version replaces lower atomically.
- Lower or equal version re-push → return 409, keep current.

---

## 4. Dataset Analysis

### Entities and Relationships

```
Category (5)
  └── has many Merchants (10 per category, 50 total)
        └── has many Customers (4 per merchant avg, 200 total)
        └── has many Triggers (2+ per merchant, 100 total)
```

### Categories (5)

| Slug | Display | Tone | Key Vocab |
|---|---|---|---|
| `dentists` | Dentists | `peer_clinical` | fluoride, caries, RCT, aligner |
| `salons` | Salons & Beauty | `warm_practical` | balayage, keratin, facial |
| `restaurants` | Restaurants & Cafes | `warm_busy_practical` | covers, AOV, footfall |
| `gyms` | Gyms & Fitness | `energetic_disciplined` | membership churn, HIIT, PT |
| `pharmacies` | Pharmacies | `trustworthy_precise` | OTC, schedule H, molecule |

Each category contains:
- `voice` (tone, vocab_allowed, vocab_taboo, salutation_examples, tone_examples)
- `offer_catalog` (8 canonical offers)
- `peer_stats` (benchmarks)
- `digest` (5 weekly items: research, compliance, trend, tech, CDE)
- `patient_content_library` (3 items)
- `seasonal_beats` (3-5 seasonal patterns)
- `trend_signals` (3-5 search trends)

### Merchants (10 seed → 50 expanded)

Seed merchants with rich data:

| ID | Name | Category | City | Key Signals |
|---|---|---|---|---|
| m_001 | Dr. Meera's Dental Clinic | dentists | Delhi | stale_posts, ctr_below_peer, high_risk_adult_cohort, engaged_in_last_48h |
| m_002 | Bharat Dental Care | dentists | Mumbai | renewal_due_soon, perf_dip_severe, unverified_gbp, dormant_with_vera_14d |
| m_003 | Studio11 Family Salon | salons | Hyderabad | high_engagement, above_peer_median_calls, growing_views_7d |
| m_004 | Glamour Lounge | salons | Pune | winback_eligible, perf_dip_post_expiry, dormant_with_vera_38d |
| m_005 | SK Pizza Junction | restaurants | Delhi | new_merchant, trial_ending_soon, ipl_eligible_locality |
| m_006 | Mylari South Indian Cafe | restaurants | Bangalore | high_volume, stable_growth, engaged_in_last_24h |
| m_007 | PowerHouse Fitness | gyms | Bangalore | seasonal_dip_apr_may, above_peer_ctr, no_recent_post |
| m_008 | Zen Yoga Studio | gyms | Chennai | high_retention, active_planning, boutique_segment |
| m_009 | Apollo Health Plus | pharmacies | Jaipur | above_peer_calls, compliance_aware, high_repeat_rate |
| m_010 | Sunrise Medicos | pharmacies | Lucknow | unverified_gbp, no_active_offers, delivery_not_set_up |

Key merchant fields: `merchant_id`, `category_slug`, `identity` (name, city, locality, verified, languages, owner_first_name), `subscription`, `performance` (views, calls, ctr, delta_7d), `offers`, `conversation_history`, `customer_aggregate`, `signals`, `review_themes`.

### Customers (15 seed → 200 expanded)

Rich seed customers include Priya (lapsed_soft dental patient), Rohit (active root canal patient), Kavya (bride-to-be), Mr. Sharma (senior citizen chronic Rx), etc.

Key fields: `customer_id`, `merchant_id`, `identity` (name, language_pref, age_band), `relationship` (visits, services, lifetime_value), `state` (new/active/lapsed_soft/lapsed_hard/churned), `preferences`, `consent`.

### Triggers (25 seed → 100 expanded)

Cover 15+ kinds:

| Kind | Scope | Source | Examples |
|---|---|---|---|
| `research_digest` | merchant | external | JIDA fluoride study |
| `regulation_change` | merchant | external | DCI radiograph limits |
| `recall_due` | customer | internal | Priya 6-month cleaning |
| `perf_dip` | merchant | internal | Bharat calls -50% |
| `renewal_due` | merchant | internal | Bharat 12 days left |
| `festival_upcoming` | merchant | external | Diwali |
| `wedding_package_followup` | customer | internal | Kavya bridal |
| `curious_ask_due` | merchant | internal | Weekly ask |
| `winback_eligible` | merchant | internal | Glamour expired |
| `ipl_match_today` | merchant | external | DC vs MI |
| `review_theme_emerged` | merchant | internal | Late delivery |
| `milestone_reached` | merchant | internal | 150 reviews |
| `active_planning_intent` | merchant | internal | Corporate thali |
| `seasonal_perf_dip` | merchant | internal | April gym dip |
| `customer_lapsed_hard` | customer | internal | Rashmi 57 days |
| `supply_alert` | merchant | external | Atorvastatin recall |
| `chronic_refill_due` | customer | internal | Mr. Sharma meds |
| `gbp_unverified` | merchant | internal | Sunrise unverified |
| `cde_opportunity` | merchant | external | IDA webinar |
| `competitor_opened` | merchant | external | Smile Studio 1.3km |
| `perf_spike` | merchant | internal | Zen calls +15% |
| `dormant_with_vera` | merchant | internal | Glamour 38 days silent |
| `trial_followup` | customer | internal | Karthik Jr yoga |
| `category_seasonal` | merchant | external | Summer demand shift |

### Deterministic Generation

`generate_dataset.py` uses seed `20260426`. Running it produces exactly the same 50 merchants, 200 customers, 100 triggers, and 30 test pairs for everyone.

### Test Pairs

30 canonical `(merchant_id, trigger_id)` pairs — up to 2 per trigger kind. These are the like-for-like comparison set.

---

## 5. Decision Engine Design

### Overview

The decision engine has two stages:
1. **Signal Extraction & Prioritization** (deterministic) — decides *what* to talk about
2. **Message Composition** (LLM-assisted) — decides *how* to say it

### Signal Extraction

For each trigger in `available_triggers`:

1. **Resolve context**: Look up trigger → merchant → category → customer (if scoped)
2. **Extract signals from merchant**: `signals[]`, `performance.delta_7d`, `conversation_history`, `review_themes`
3. **Cross-reference with category**: `peer_stats` (is this merchant above/below?), `digest` items, `seasonal_beats`
4. **Check suppression**: Has this `suppression_key` already been sent? Skip if yes.
5. **Check expiry**: Is `expires_at` past `now`? Skip if yes.
6. **Check freshness**: Is the trigger context still current version?

### Signal Prioritization

Rank triggers by composite score:

```python
priority = (
    urgency * 3                          # trigger urgency (1-5)
    + recency_bonus                      # recent context update = +2
    + engagement_bonus                   # merchant replied recently = +2
    - dormancy_penalty                   # merchant dormant = -1 (be cautious)
    + category_seasonal_match            # seasonal beat active = +1
    - suppression_penalty                # similar key recently = skip entirely
)
```

**Critical rule**: Choose the SINGLE most important trigger per merchant per tick. Don't dump all signals into one message.

### Trigger Handling by Kind

| Kind | Strategy |
|---|---|
| `research_digest` | Lead with the specific study finding, cite source, offer to pull/draft |
| `recall_due` | Customer-facing, specific dates + price, multi-choice slot |
| `perf_dip` | Contextualize (seasonal vs real), offer specific action |
| `perf_spike` | Celebrate, attribute likely driver, suggest capitalizing |
| `renewal_due` | Concrete value delivered + what they'd lose |
| `festival_upcoming` | Only if actionable; skip if too far out |
| `ipl_match_today` | Counter-intuitive data-informed recommendation |
| `review_theme_emerged` | Surface the theme, offer concrete fix |
| `active_planning_intent` | Draft the actual artifact, don't ask more questions |
| `supply_alert` | Urgent, specific batch numbers, offer workflow |
| `chronic_refill_due` | Customer-facing, molecule names, total + savings |
| `competitor_opened` | Voyeur-curiosity framing, not panic |
| `curious_ask_due` | Ask the merchant a question, offer reciprocity |
| `winback_eligible` | Frame what they've lost since expiry |
| `customer_lapsed_hard` | No-shame, address past goal, specific new offering |

### Merchant Fit

- Use `owner_first_name` in salutation (not generic "Hi")
- Use actual `performance` numbers (views, calls, ctr)
- Reference actual `offers` (active only!)
- Honor `languages` preference (hi-en mix for Hindi speakers)
- Reference `review_themes` if relevant
- Use `customer_aggregate` stats (lapsed count, retention %)

### Category Fit

- Match `voice.tone` — peer_clinical for dentists, warm_practical for salons, etc.
- Use `vocab_allowed` terms
- Avoid `vocab_taboo` terms
- Reference `peer_stats` for comparison anchors
- Use `digest` items when trigger references them
- Apply `seasonal_beats` awareness

### Specificity

- Always include at least one concrete number from the contexts
- Cite sources for research/compliance items
- Use real offer prices, not percentages
- Reference real dates, localities, merchant names
- **Never fabricate data** — if it's not in context, don't invent it

### Engagement / CTA

- End with a single, low-friction CTA
- Binary (YES/STOP) for action triggers
- Open-ended for curiosity/research triggers
- No CTA for pure-information triggers
- Frame as effort externalization: "Want me to draft X?"

### Suppression

Track `suppression_key` → `sent_at` in state. Skip triggers whose key has been sent. Clear suppression state only on explicit merchant re-engagement or after configurable TTL.

### Stale Context Handling

Always use the highest-version context. If a category gets version-bumped mid-test with new digest items, the next composition must use the new items.

### Conversation Handling (Multi-Turn)

| Merchant Signal | Bot Action |
|---|---|
| Engaged reply ("Yes", "Send it", etc.) | Switch to action mode, deliver artifact |
| Auto-reply (canned text) | Acknowledge once → wait → end after 3x |
| Hard no ("Stop messaging") | Graceful exit, suppress merchant |
| Off-topic question ("Help with GST?") | Politely decline, redirect to original topic |
| Commitment ("Let's do it") | Execute immediately, don't re-qualify |
| Silence (no reply) | Don't re-send; use next tick to try different trigger |

---

## 6. LLM Strategy

### Comparison

| Approach | Pros | Cons |
|---|---|---|
| **Fully rule-based** | Fast, deterministic, no API cost | Can't produce natural language, poor category voice variation, rigid |
| **LLM-only** | Natural language, flexible | Slow, expensive, prone to hallucination, poor at structured decisions |
| **Hybrid** ✅ | Best of both: deterministic decisions + natural language | Slightly more complex architecture |

### Recommended Hybrid Architecture

```
Trigger arrives
    │
    ▼
[Deterministic Decision Engine]       ← NO LLM
    ├── Resolve contexts
    ├── Check suppression/expiry
    ├── Rank signals
    ├── Select best trigger
    ├── Extract key facts
    ├── Determine send_as, cta type
    └── Build structured prompt input
    │
    ▼
[LLM Composer]                        ← LLM HERE
    ├── Receives: category voice rules, merchant facts, trigger payload, customer data
    ├── Prompt variant selected by trigger.kind
    ├── Temperature: 0.3 (some creativity, mostly grounded)
    └── Returns: body text
    │
    ▼
[Post-LLM Validator]                  ← NO LLM
    ├── Check body for vocab_taboo words
    ├── Check body for URLs (hard fail)
    ├── Check body for fabricated numbers (not in input)
    ├── Check CTA is present and at end
    ├── Check language match
    └── Re-prompt if validation fails (1 retry)
```

### Where LLM Is Used

1. **Message body composition** — translating structured facts into natural, category-appropriate WhatsApp copy
2. **Reply composition** — handling merchant replies in context-aware, natural language
3. **Auto-reply detection** — pattern matching handles most cases, but LLM can handle edge cases

### Where LLM Is NOT Used

1. **Trigger selection/prioritization** — deterministic rules
2. **Suppression checking** — simple key lookup
3. **Context versioning** — simple comparison
4. **CTA type selection** — rule-based by trigger kind
5. **send_as determination** — rule-based by trigger scope
6. **Fact extraction** — direct field access from context payloads

### Model Recommendation

- **Primary**: `gpt-4o-mini` or `gemini-1.5-flash` — fast, cheap, good quality for structured prompting
- **Fallback**: `gpt-4o` for complex cases (active_planning_intent with artifact drafting)
- **Temperature**: 0.2-0.3 for composition, 0.0 for validation

---

## 7. System Architecture

### Project Structure

```
vera-bot/
├── main.py                    # FastAPI app entry point
├── config.py                  # Environment variables, constants
├── requirements.txt           # Dependencies
├── Dockerfile                 # Container for deployment
│
├── api/                       # HTTP layer
│   ├── __init__.py
│   ├── routes.py              # All 5 endpoint handlers
│   ├── schemas.py             # Pydantic models for request/response
│   └── middleware.py          # Logging, error handling, timing
│
├── state/                     # Context & conversation storage
│   ├── __init__.py
│   ├── store.py               # ContextStore class (in-memory dict)
│   └── models.py              # Internal data models
│
├── engine/                    # Decision engine
│   ├── __init__.py
│   ├── decision.py            # Trigger ranking, signal extraction
│   ├── suppression.py         # Suppression key tracking
│   └── conversation.py        # Multi-turn state machine
│
├── composer/                  # Message composition
│   ├── __init__.py
│   ├── composer.py            # Main compose() function
│   ├── prompts.py             # Prompt templates by trigger kind
│   ├── validator.py           # Post-LLM output validation
│   └── reply_composer.py      # Reply handling composition
│
├── llm/                       # LLM adapter
│   ├── __init__.py
│   └── client.py              # LLM API wrapper (multi-provider)
│
└── tests/                     # Test suite
    ├── test_api.py
    ├── test_engine.py
    ├── test_composer.py
    └── test_integration.py
```

### Component Diagram

```
                    ┌─────────────────────────────────────────┐
                    │              HTTP Layer (FastAPI)        │
                    │  /healthz  /metadata  /context          │
                    │  /tick     /reply                        │
                    └────────┬──────────┬──────────┬──────────┘
                             │          │          │
                    ┌────────▼──┐  ┌────▼────┐  ┌─▼──────────┐
                    │  Context  │  │Decision │  │Conversation│
                    │  Store    │  │ Engine  │  │  Manager   │
                    │           │  │         │  │            │
                    │ categories│  │ rank    │  │ turns[]    │
                    │ merchants │  │ filter  │  │ state      │
                    │ customers │  │ select  │  │ auto-reply │
                    │ triggers  │  │         │  │ detection  │
                    └─────┬─────┘  └────┬────┘  └─────┬──────┘
                          │             │             │
                          └──────┬──────┘             │
                                 │                    │
                          ┌──────▼────────────────────▼──┐
                          │       Message Composer        │
                          │  prompt_builder → LLM → validator │
                          └──────────────┬───────────────┘
                                         │
                                  ┌──────▼──────┐
                                  │  LLM Client │
                                  │ (OpenAI/etc) │
                                  └─────────────┘
```

---

## 8. Database / State

### What State Must Persist

| State | Why | Structure |
|---|---|---|
| **Contexts** | Judge pushes context, we must remember it for composition | `Dict[(scope, context_id)] → {version, payload, delivered_at}` |
| **Conversations** | Multi-turn requires knowing what was said before | `Dict[conversation_id] → {merchant_id, customer_id, turns[], state}` |
| **Suppression keys** | Don't re-send the same trigger | `Set[suppression_key] → sent_at` |
| **Sent message bodies** | Anti-repetition check per conversation | Stored in conversation turns |

### Storage Solution: In-Memory Python Dicts

**Rationale**: The challenge brief explicitly says "Storing in memory is fine; just don't restart between calls." The test window is 60 simulated minutes. No persistence needed across restarts.

```python
# Core state
contexts: dict[tuple[str, str], ContextEntry] = {}      # (scope, context_id) → {version, payload}
conversations: dict[str, Conversation] = {}               # conversation_id → conversation state
suppressed_keys: set[str] = set()                          # suppression_key → already sent
suppressed_merchants: set[str] = set()                     # merchant_id → opted out
```

### Version Handling

```python
def accept_context(scope, context_id, version, payload, delivered_at):
    key = (scope, context_id)
    current = contexts.get(key)
    if current and current.version >= version:
        return False, current.version  # 409
    contexts[key] = ContextEntry(version=version, payload=payload, delivered_at=delivered_at)
    return True, version  # 200
```

### Conversation History

```python
@dataclass
class ConversationTurn:
    role: str          # "vera" or "merchant"
    body: str
    timestamp: str
    turn_number: int

@dataclass
class Conversation:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    trigger_id: str
    turns: list[ConversationTurn]
    state: str         # "active", "waiting", "ended"
    auto_reply_count: int = 0
```

### Idempotency

Context pushes are idempotent by `(context_id, version)` — same version re-push returns 409. Higher version replaces. This is handled by the simple version comparison above.

---

## 9. Implementation Order

### Phase 1: Project Setup (30 min)

- [ ] Create project directory structure
- [ ] Set up `requirements.txt` (fastapi, uvicorn, httpx/openai/anthropic, pydantic)
- [ ] Create `config.py` with env vars (PORT, LLM_API_KEY, LLM_MODEL, LLM_PROVIDER)
- [ ] Create `main.py` with FastAPI app
- [ ] Verify: `uvicorn main:app --port 8080` starts

**Test**: Server starts, returns 404 on unknown routes.

### Phase 2: API Skeleton (1 hour)

- [ ] Implement `GET /v1/healthz` — return hardcoded OK
- [ ] Implement `GET /v1/metadata` — return team info
- [ ] Implement `POST /v1/context` — accept and store (basic)
- [ ] Implement `POST /v1/tick` — return `{"actions": []}`
- [ ] Implement `POST /v1/reply` — return `{"action": "end"}`
- [ ] Add Pydantic schemas for all request/response bodies

**Test**: `curl` all 5 endpoints. Run `judge_simulator.py` warmup scenario.

### Phase 3: Context Store + Version Handling (1 hour)

- [ ] Implement `ContextStore` class with in-memory dicts
- [ ] Implement version comparison logic (accept higher, reject same/lower)
- [ ] Update `/v1/healthz` to return real `contexts_loaded` counts
- [ ] Update `/v1/context` to use ContextStore with proper 200/400/409 responses
- [ ] Add scope validation (must be category/merchant/customer/trigger)

**Test**: Push contexts, verify counts. Push same version → 409. Push higher version → 200.

### Phase 4: Decision Engine (2 hours)

- [ ] Implement trigger resolution (trigger → merchant → category → customer)
- [ ] Implement suppression checking
- [ ] Implement trigger ranking by urgency + signals
- [ ] Implement `send_as` determination (vera vs merchant_on_behalf)
- [ ] Implement CTA type selection by trigger kind
- [ ] Update `/v1/tick` to select and return actions (with placeholder body text)

**Test**: Push full dataset, call tick with triggers, verify actions have correct merchant_id, trigger_id, send_as, cta.

### Phase 5: LLM Integration + Message Composition (3 hours)

- [ ] Implement LLM client wrapper (support OpenAI, Anthropic, Gemini)
- [ ] Design prompt templates for each trigger kind family
- [ ] Implement main `compose()` function
- [ ] Implement post-LLM validator (check taboo words, URLs, fabrication)
- [ ] Wire composer into `/v1/tick` handler
- [ ] Generate `conversation_id`, `suppression_key`, `template_name`, `template_params`

**Test**: Full tick with real LLM composition. Verify message quality against case studies.

### Phase 6: Conversation / Reply Handling (2 hours)

- [ ] Implement conversation state management (create on tick, update on reply)
- [ ] Implement auto-reply detection (pattern matching + counter)
- [ ] Implement intent transition detection ("yes" / "let's do it" → action mode)
- [ ] Implement hostile/opt-out detection → graceful end
- [ ] Implement off-topic detection → polite redirect
- [ ] Implement reply composition with conversation history context
- [ ] Wire into `/v1/reply` handler

**Test**: Run `judge_simulator.py` auto_reply, intent, hostile scenarios.

### Phase 7: Polish + Edge Cases (1 hour)

- [ ] Handle unknown trigger IDs gracefully
- [ ] Handle missing merchant/category context gracefully
- [ ] Handle expired triggers (check `expires_at` vs `now`)
- [ ] Ensure anti-repetition (don't send same body in same conversation)
- [ ] Ensure rationale field is always meaningful and matches the message
- [ ] Add request/response logging for debugging

**Test**: Run full `judge_simulator.py` all scenario.

### Phase 8: Testing (1 hour)

- [ ] Run expanded dataset generation: `python generate_dataset.py --out expanded`
- [ ] Test with all 100 triggers
- [ ] Run `judge_simulator.py full_evaluation`
- [ ] Review scores, iterate on prompts for low-scoring dimensions
- [ ] Verify no hallucinated facts, no URLs, no repetition

### Phase 9: Deployment (30 min)

- [ ] Create Dockerfile
- [ ] Deploy to cloud (Railway/Render/Fly.io)
- [ ] Verify public URL responds to all 5 endpoints
- [ ] Run `judge_simulator.py` against public URL
- [ ] Submit URL

### Phase 10: Final Verification (30 min)

- [ ] Run full test suite against deployed endpoint
- [ ] Verify healthz shows correct counts after warmup
- [ ] Verify context version bumps are handled
- [ ] Verify conversation flows complete successfully
- [ ] Review LLM costs / rate limits are within budget

---

## 10. Test Plan

### Endpoint Tests

| Test | Endpoint | Expected |
|---|---|---|
| Healthz returns OK | GET /v1/healthz | 200, `status: "ok"` |
| Healthz shows correct counts | GET /v1/healthz (after push) | counts match pushed |
| Metadata returns team info | GET /v1/metadata | 200, has team_name |
| Context accepts valid push | POST /v1/context | 200, `accepted: true` |
| Context rejects invalid scope | POST /v1/context (scope="invalid") | 400 |
| Context rejects stale version | POST /v1/context (same version) | 409, `stale_version` |
| Context accepts version bump | POST /v1/context (higher version) | 200 |
| Tick returns empty when no triggers | POST /v1/tick (no triggers) | 200, `actions: []` |
| Tick returns actions for valid triggers | POST /v1/tick (with triggers) | 200, actions with required fields |
| Tick respects suppression | POST /v1/tick (already suppressed) | 200, `actions: []` |
| Reply handles engaged merchant | POST /v1/reply ("Yes") | 200, `action: "send"` |
| Reply handles auto-reply | POST /v1/reply (canned text) | 200, `action: "send"` or `"wait"` |
| Reply handles hostile | POST /v1/reply ("Stop") | 200, `action: "end"` |
| Reply handles off-topic | POST /v1/reply ("Help with GST") | 200, `action: "send"` (redirect) |
| Reply handles intent transition | POST /v1/reply ("Let's do it") | 200, `action: "send"` (action mode) |

### Quality Tests

| Test | What We Check |
|---|---|
| No hallucinated numbers | Body contains only numbers from input contexts |
| No URLs in body | No `http://` or `https://` |
| No vocab_taboo words | Body doesn't contain category taboo terms |
| Owner name used | Body contains `owner_first_name` |
| Category voice match | Tone appropriate for category |
| CTA at end | Last sentence is the call-to-action |
| Language match | Hindi-English mix for merchants with `hi` in languages |
| No repetition | Same body not sent twice in same conversation |
| Rationale matches body | Rationale accurately describes what the message does |
| Suppression works | Same trigger not acted on twice |

### Scenario Tests (via judge_simulator.py)

1. `warmup` — healthz + metadata + context push
2. `phase2_short` — context push + tick + scoring
3. `auto_reply_hell` — 4x auto-reply detection
4. `intent_transition` — commitment → action mode
5. `hostile` — hostile handling
6. `all` — all above combined
7. `full_evaluation` — all triggers scored

---

## 11. Deployment

### Requirements for Evaluator Access

1. **Public URL**: `https://<host>/v1/*` or `http://<host>/v1/*`
2. **5 endpoints responding**: healthz, metadata, context, tick, reply
3. **Stable uptime**: No restarts during 60-min test window
4. **Sub-30s response times**: All endpoints must respond within 30s

### Environment Variables

```
PORT=8080
LLM_PROVIDER=openai          # or anthropic, gemini
LLM_API_KEY=sk-...           # API key
LLM_MODEL=gpt-4o-mini        # or specific model
LOG_LEVEL=INFO
```

### Startup Command

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Health Check

The judge calls `GET /v1/healthz` every 60s. Must return 200 with correct `contexts_loaded` counts.

### Recommended Deployment Targets

1. **Railway** — easiest, auto-deploy from Git, free tier available
2. **Render** — similar to Railway
3. **Fly.io** — good for low-latency
4. **ngrok** — for local development testing only

### Compute Budget

- LLM API: ~100 tick actions × $0.01/call = ~$1 for gpt-4o-mini
- Server: minimal compute (FastAPI handles 10 req/s easily)
- Memory: <100MB for full dataset in memory

---

## 12. Failure Risks

### API Failures

| Risk | Impact | Mitigation |
|---|---|---|
| Server crash mid-test | Disqualification | Catch all exceptions, never crash |
| Timeout on `/v1/tick` | -1 penalty per timeout | Set LLM timeout to 15s; return empty actions on timeout |
| Malformed JSON response | -2 penalty per malformed | Pydantic models enforce schema |
| Missing required fields on actions | 0 score + -2 penalty | Validate all required fields before returning |

### Protocol Failures

| Risk | Impact | Mitigation |
|---|---|---|
| Not storing context versions | Using stale data | Version comparison on every push |
| Not tracking suppression | Repeated messages | Suppression key set |
| Not counting contexts | Warmup failure | Increment counters on each accepted push |
| Reusing conversation_id in tick | Invalid action | Generate unique IDs per tick |

### State Errors

| Risk | Impact | Mitigation |
|---|---|---|
| Context overwritten incorrectly | Stale/wrong data | Atomic replace, version check |
| Conversation state lost | Broken multi-turn | Never clear conversations during test |
| Auto-reply counter reset | Bot wastes turns | Counter on conversation object, not global |

### Low Judge Scores

| Risk | Impact | Mitigation |
|---|---|---|
| Generic copy ("increase your sales") | Low specificity score | Always include concrete numbers from context |
| Wrong category voice | Low category fit | Voice rules in prompt per category |
| Hallucinated facts | Fabrication penalty (-2) | Validator checks numbers against input |
| Multiple CTAs | Low engagement score | Enforce single CTA rule |
| Promotional tone for clinical categories | Low category fit | Taboo word filter + prompt guidance |
| Ignoring language preference | Low merchant fit | Check `identity.languages`, code-mix prompt |
| Not using owner name | Low merchant fit | Always extract and use `owner_first_name` |
| Long preamble | Penalized | Prompt instruction: no "I hope you're doing well" |

### Conversation Handling Failures

| Risk | Impact | Mitigation |
|---|---|---|
| Not detecting auto-reply | Wasted turns | Pattern match canned phrases |
| Re-qualifying after commitment | Penalty for ignoring intent | Detect "yes"/"let's do it" → action mode |
| Not exiting on hostility | Bad conversation score | Detect hostility → end |
| Responding to off-topic | Off-mission | Detect → politely decline → redirect |

---

## 13. Final Checklist

Based only on actual challenge files:

### Pre-Submission

- [ ] Endpoint reachable from public internet (HTTPS or HTTP)
- [ ] All 5 endpoints implemented and returning correct schemas:
  - [ ] `GET /v1/healthz` → `{status, uptime_seconds, contexts_loaded}`
  - [ ] `GET /v1/metadata` → `{team_name, model, version, ...}`
  - [ ] `POST /v1/context` → `{accepted, ack_id, stored_at}` or `{accepted: false, reason, current_version}`
  - [ ] `POST /v1/tick` → `{actions: [...]}`
  - [ ] `POST /v1/reply` → `{action: "send"|"wait"|"end", ...}`
- [ ] `/v1/context` is idempotent on `(scope, context_id, version)`
- [ ] `/v1/context` returns 409 for same or lower version
- [ ] `/v1/context` replaces atomically on higher version
- [ ] `/v1/tick` returns within 30s (returns `{"actions": []}` if needed)
- [ ] `/v1/reply` returns within 30s for any conversation
- [ ] Bot persists context across calls (in-memory OK, no restarts)
- [ ] `contexts_loaded` counts match what judge pushed
- [ ] Action objects contain ALL required fields: `conversation_id`, `merchant_id`, `send_as`, `trigger_id`, `body`, `cta`, `suppression_key`, `rationale`
- [ ] No URLs in message bodies
- [ ] No fabricated data in messages
- [ ] No vocab_taboo words in messages
- [ ] Owner/merchant first name used when available
- [ ] Language preference honored (Hindi-English code-mix)
- [ ] Category voice/tone matches
- [ ] Single CTA per message, at end
- [ ] Suppression keys prevent re-sends
- [ ] Anti-repetition: no duplicate body in same conversation
- [ ] Auto-reply detection works (acknowledge once → wait → end)
- [ ] Intent transition detection works (commitment → action mode)
- [ ] Hostile/opt-out handling works (graceful exit)
- [ ] `rationale` field is meaningful and matches the message
- [ ] `judge_simulator.py` passes locally with non-zero scores
- [ ] Compute budget set (LLM API quota survives 60-min test)
- [ ] Submitted URL via submission portal

### Quality Bar (from Case Studies)

- [ ] Messages score 7+ on all 5 dimensions consistently
- [ ] Specificity: concrete numbers, dates, sources from context
- [ ] Category fit: correct vocabulary, tone, no overclaims
- [ ] Merchant fit: personalized to THIS merchant's data
- [ ] Trigger relevance: clear "why now" connected to trigger
- [ ] Engagement compulsion: low-friction CTA, compulsion levers used
