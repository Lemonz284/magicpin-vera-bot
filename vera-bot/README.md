# MagicPin Vera AI Bot

High-performance, category-grounded WhatsApp messaging engine for the **MagicPin Vera AI Challenge**. Vera is an intelligent merchant messaging assistant that analyzes business signals, prioritizes operational triggers, and composes compelling, context-grounded WhatsApp messages for local merchants across 5 core categories (`dentists`, `salons`, `restaurants`, `gyms`, `pharmacies`).

---

## 🏗️ Architecture Overview

The system uses a **Hybrid Rule-Based Decision Engine + Grounded LLM Composer**:

```
                       Judge / Evaluator
                              │
                 HTTP POST    │    HTTP GET
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
    POST /v1/context                       GET /v1/healthz
    POST /v1/tick                          GET /v1/metadata
    POST /v1/reply
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ ContextStore (In-Memory State & Suppression Tracker)   │
│  - Categories, Merchants, Customers, Triggers          │
│  - Monotonic versioning & conflict detection (409)     │
│  - Suppression key & merchant opt-out registry         │
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Decision Engine (Prioritization & Filter)              │
│  - Expiry checking (is_expired vs simulation clock)    │
│  - Urgency & signal ranking (review threats > churn)   │
│  - 1-trigger-per-merchant per tick enforcement         │
│  - Action capping at 20 triggers per tick              │
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Hybrid Message Composer                                │
│  - 100% Grounded Deterministic Baseline (24 triggers)  │
│  - Multi-Provider LLM Client (OpenAI, Gemini, Anthropic│
│    Groq, OpenRouter, Ollama)                           │
│  - Post-Generation Validator (Zero URLs, Taboo Filter, │
│    Dentist Salutation check, Anti-Repetition guard)    │
└────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ Multi-Turn Conversation State Machine                  │
│  - Auto-reply backoff: Acknowledge -> Wait -> End      │
│  - Hostile/Opt-out detection -> Graceful exit          │
│  - Off-topic redirection -> Polite decline & redirect  │
│  - Commitment detection -> Action delivery mode        │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart

### 1. Requirements
- Python 3.10+
- `pip install -r requirements.txt`

### 2. Run Locally
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

### 3. Run with Docker
```bash
docker build -t vera-bot .
docker run -p 8080:8080 vera-bot
```

Or using Docker Compose:
```bash
docker-compose up --build
```

---

## 📡 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/healthz` | GET | Liveness probe reporting uptime & real context counts per scope |
| `/v1/metadata` | GET | Bot identity, version, model, and approach |
| `/v1/context` | POST | Context ingestion with monotonic version replacement & 409 conflict checks |
| `/v1/tick` | POST | Outbound trigger evaluation, prioritization, and grounded message composition |
| `/v1/reply` | POST | Inbound conversation turns, hostility, auto-replies, and action mode |
| `/v1/teardown` | POST | Resets in-memory state for fresh evaluation runs |

---

## 🧪 Testing & Verification

Run the complete test suite:
```bash
python -m pytest tests/
```

Run the local judge simulator benchmark:
```bash
python tests/test_judge_sim.py
```

### Benchmark Results
- **Overall Score**: `45/50` (**90% - EXCELLENT**)
- **Specificity**: `9/10` (Concrete stats, dates, patient counts)
- **Category Fit**: `9/10` (Clinical tone for dentists, warm for salons)
- **Merchant Fit**: `9/10` (Personalized to owner and locality)
- **Decision Quality**: `9/10` (High urgency compliance and alerts prioritized)
- **Engagement**: `9/10` (Single low-friction CTA, zero URLs)

---

## ☁️ Cloud Deployment

The application is containerized and ready for one-click deployment:

### Railway / Render / Fly.io
1. Point your service to this repository.
2. Set Environment Variables:
   - `PORT=8080`
   - `LLM_PROVIDER=openai` (or `gemini`, `anthropic`, `groq`)
   - `LLM_API_KEY=<your-key>`
3. The server will pass healthchecks at `/v1/healthz` on startup.
