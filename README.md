# WhatsApp Lead CRM

A lightweight Python service that turns WhatsApp Business messages into structured CRM leads — automatically parsed by Gemini AI and saved to Google Sheets in real time.

**Live demo:** [your-railway-url.up.railway.app](https://your-url.up.railway.app)  
**Built by:** Jatin | B.Tech CSE 2027

---

## The problem

Small businesses and freelancers receive dozens of enquiries on WhatsApp every day. Most of them get lost in chat — no follow-up system, no history, no priority. This tool acts as an always-on receptionist: it reads every inbound message, extracts what the person wants, and logs it as a structured lead in a Google Sheet your team can act on.

---

## How it works

```
WhatsApp message received
        ↓
Meta Cloud API sends webhook → FastAPI server
        ↓
Gemini Flash extracts: name, topic, intent, urgency, summary
        ↓
Lead row appended to Google Sheet (with timestamp, status)
        ↓
Auto-reply sent back to the user via WhatsApp
```

---

## Tech stack

| Layer | Tool |
|---|---|
| Runtime | Python 3.12 |
| Web framework | FastAPI + Uvicorn |
| AI parsing | Google Gemini Flash 1.5 |
| Messaging | WhatsApp Cloud API (Meta) |
| Data store | Google Sheets API v4 |
| Auth | Google Service Account |
| Deploy | Railway |

---

## Setup (local)

### 1. Clone and install

```bash
git clone https://github.com/yourusername/whatsapp-crm.git
cd whatsapp-crm
pip install -r requirements.txt
```

### 2. Set up credentials

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

You need:
- **WhatsApp Cloud API token + Phone Number ID** — from [Meta Developer Console](https://developers.facebook.com) → Create App → WhatsApp → API Setup
- **Gemini API key** — from [Google AI Studio](https://aistudio.google.com/app/apikey) (free)
- **Google Sheet ID** — the ID from your Sheet URL
- **Google Service Account JSON** — from Google Cloud Console → IAM → Service Accounts → create key → download JSON → save as `config/service_account.json`

> Share your Google Sheet with the service account email (e.g. `bot@project.iam.gserviceaccount.com`) with Editor access.

### 3. Run locally

```bash
python main.py
```

Server starts at `http://localhost:8000`

### 4. Expose locally for webhook testing

```bash
# Install ngrok, then:
ngrok http 8000
```

Use the ngrok HTTPS URL as your webhook in Meta Console: `https://xxxx.ngrok.io/webhook`

---

## Deploy to Railway (5 minutes)

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add all your `.env` variables in Railway's Variables tab
4. For `service_account.json`: paste the entire JSON content as an env variable named `GOOGLE_SERVICE_ACCOUNT_JSON`, then update `sheets.py` to load from that env var instead of a file
5. Railway auto-deploys on every push — your live URL is your webhook URL

---

## Google Sheet structure

The sheet auto-creates this header row on first run:

| Timestamp | Name | Phone | Topic | Intent | Urgency | Summary | Raw Message | Status | Source |
|---|---|---|---|---|---|---|---|---|---|
| 2024-05-01 10:23 | Rahul Sharma | 919876543210 | Pricing for web design | purchase | high | Wants a quote for a 5-page website | "Hi how much for a website?" | New | WhatsApp |

---

## What I learned building this

- Meta's webhook verification requires an immediate `200 OK` with the challenge string — any async delay causes verification to fail
- Gemini's response sometimes wraps JSON in markdown fences even when told not to — added a `.removeprefix("```json")` strip as a fallback
- Google Sheets API auth with service accounts requires the sheet to be explicitly shared with the service account email — this trips up most first-timers
- Railway's `$PORT` env var overrides your hardcoded port — the `railway.toml` handles this

---

## Roadmap

- [ ] PostgreSQL lead history with deduplication by phone number
- [ ] Slack notification on high-urgency leads  
- [ ] Dashboard via Google Data Studio connected to the same Sheet
- [ ] Multi-language support using Gemini's translation capability
