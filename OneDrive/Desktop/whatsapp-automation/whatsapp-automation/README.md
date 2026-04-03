# WhatsApp Recruitment Outreach Automation

> Automate your entire candidate outreach pipeline on WhatsApp — from first message to follow-up to reply classification — without lifting a finger.

A structured, human-like 3-touch outreach engine that runs on WhatsApp Web, tracks every candidate in a Google Sheet, classifies replies with AI, and keeps your team in the loop automatically via Telegram.

---

## Why This Exists

Most ATS tools ignore WhatsApp — the channel where candidates actually respond. Cold emails get ignored. LinkedIn InMails go unread. WhatsApp gets opened.

This tool bridges that gap: it runs a structured, human-like outreach sequence on WhatsApp Web, tracks every candidate in a Google Sheet, and keeps your HR team in the loop automatically.

---

## What It Does

- Sends a 3-message outreach sequence (Msg1 → Msg2 → Msg3) with 36-hour follow-up gaps
- Detects replies using smart baseline diffing — no polling hacks
- Classifies replies as **Positive / Negative / Neutral** using the Grok AI API (xAI) with keyword fallback
- Notifies HR instantly via **Telegram** (zero WhatsApp budget cost)
- Sends a daily EOD email report with campaign stats
- Respects working hours (9 AM–9 PM), skips Sundays, enforces a 20 msg/day anti-ban limit
- Fully controllable via a **Telegram bot** — start campaigns, check status, view logs, all from your phone
- Persists state across restarts — resume mid-campaign with `--resume`

---

## Architecture

```
send_queue ──► sender_worker   (only thread that touches WhatsApp Web)
                    │
monitor_worker ─────┘  (checks replies, queues follow-ups — never sends directly)
                    │
report_worker ──────┘  (sends 7 PM EOD email)
```

Single-sender architecture eliminates race conditions. All follow-ups are queued, not sent directly, so timing and anti-ban logic is centralised.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Outreach channel | WhatsApp Web (Selenium + Chrome) |
| Candidate data | Google Sheets API |
| Reply classification | Grok API (xAI) / keyword fallback |
| HR notifications | Telegram Bot API |
| Email reports | Gmail SMTP (App Password) |
| Language | Python 3.10+ |

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/your-username/whatsapp-automation.git
cd whatsapp-automation
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Google Sheets API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → enable **Google Sheets API** and **Google Drive API**
3. Create an **OAuth 2.0 Client ID** (Desktop app)
4. Download the JSON → rename to `credentials.json` and place it in the project folder
5. Run `python3 setup_sheets.py` to authenticate (one-time browser login)

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
SHEET_ID=
OUTREACH_NUMBER=
HR_NUMBER=
CHROME_PROFILE_DIR=
GROK_API_KEY=
GMAIL_SENDER=
GMAIL_APP_PASSWORD=
REPORT_RECIPIENTS=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_IDS=
HR_TELEGRAM_IDS=
```

### 5. Set up your Google Sheet

Your sheet needs these columns (exact names):

| Column | Description |
|---|---|
| `Name` | Candidate full name |
| `Contact` | Candidate phone number (international format) |
| `Role` | Role they're being considered for |
| `Status` | Auto-managed by the bot |
| `HR Notified` | Auto-managed by the bot |
| `Reply Type` | Auto-added if missing |
| `Msg1 Sent` / `Msg2 Sent` / `Msg3 Sent` | Auto-added if missing |

### 6. Customise your message templates

Edit `templates.txt`:

```
[MSG1]
Hey {name} - quick note from [Your Company]. We're hiring for {role} roles and thought you'd be a great fit. Are you open to exploring?

[MSG2]
Hi {name} - following up on my last message. Happy to share more details on the {role} opportunity if you're interested.

[MSG3]
Hey {name} - closing the loop here. Let me know if you'd like to connect, else no worries at all!
```

---

## Usage

### Interactive mode (recommended for first run)

```bash
python3 main.py
```

Walks you through tab selection, row range, candidate count, and role — then shows a preview before sending anything.

### Resume a paused campaign

```bash
python3 main.py --resume
```

### Test Google Sheets connection

```bash
python3 main.py --setup
```

### Control via Telegram bot

Start the bot:

```bash
python3 bot.py
```

Available commands:

| Command | Action |
|---|---|
| `/newcampaign` | Start a new outreach campaign (guided) |
| `/start` | Resume from last saved state |
| `/stop` | Stop the running automation |
| `/status` | Live pipeline summary |
| `/report` | Trigger EOD email report now |
| `/logs` | Last 25 lines of today's log |

---

## Anti-Ban & Safety

This tool is designed to mimic human behaviour:

- Human-like typing speed (40–80 WPM) with random typos and corrections
- Random pre-chat pauses (3–12s) and distraction pauses (8–90s)
- 5–12 min gap between messages within a batch
- 30–50 min gap between Msg1/Msg2/Msg3 batches
- Hard cap of 20 messages/day
- No sends on Sundays or outside 9 AM–9 PM
- Defers remaining queue to next day if daily limit is hit

---

## Project Structure

```
whatsapp-automation/
├── main.py           # Orchestrator — sender, monitor, report workers
├── bot.py            # Telegram bot control interface
├── whatsapp.py       # WhatsApp Web automation (Selenium)
├── sheets.py         # Google Sheets read/write
├── classifier.py     # Reply classification (Grok API + keyword fallback)
├── email_report.py   # EOD email report
├── config.py         # All configuration (reads from env vars)
├── templates.txt     # Message templates (MSG1, MSG2, MSG3)
├── setup_sheets.py   # One-time Google auth setup
├── credentials.json  # Google OAuth template (fill in your own)
└── logs/             # Daily log files (gitignored)
```

---

## Security

- All secrets are loaded from environment variables — nothing hardcoded
- `credentials.json`, `token.pickle`, `state.json`, and `logs/` are gitignored
- See `.gitignore` for the full exclusion list

---

## Contributing

Pull requests are welcome. For major changes, open an issue first to discuss what you'd like to change.

---

## License

MIT

---

## Built By

Open source. Contributions welcome.
