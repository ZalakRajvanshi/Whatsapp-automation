"""
Configuration for WhatsApp Recruitment Outreach Automation

Copy this file to config.py and fill in your values.
NEVER commit real credentials to version control.
Use environment variables or a .env file for secrets.
"""
import os

# ── Google Sheet ────────────────────────────────────────────────────────────
SHEET_ID = os.environ.get("SHEET_ID", "YOUR_GOOGLE_SHEET_ID_HERE")

# ── WhatsApp numbers ────────────────────────────────────────────────────────
OUTREACH_NUMBER = os.environ.get("OUTREACH_NUMBER", "")
HR_NUMBER       = os.environ.get("HR_NUMBER",       "")

# ── Chrome profile path ─────────────────────────────────────────────────────
CHROME_PROFILE_DIR = os.environ.get("CHROME_PROFILE_DIR", "/path/to/your/whatsapp-chrome-profile")

# ── Follow-up timing (Production) ──────────────────────────────────────────
SEND_DELAY       = 36 * 3600  # 36 hours between follow-ups
MONITOR_INTERVAL = 10 * 60    # reply check frequency (10 min)

# ── Working hours (for follow-up scheduling) ────────────────────────────────
WORK_HOUR_START = 9   # 9 AM
WORK_HOUR_END   = 21  # 9 PM

# ── Anti-ban ────────────────────────────────────────────────────────────────
MAX_DAILY_MESSAGES          = 20
QUIET_HOUR_START            = 21
QUIET_HOUR_END              = 9
MONITOR_FULL_CHECK_INTERVAL = 1 * 3600
MONITOR_CHAT_OPEN_DELAY     = (3, 6)

# ── Batch send gaps ──────────────────────────────────────────────────────────
WITHIN_BATCH_GAP_MIN  = 5  * 60
WITHIN_BATCH_GAP_MAX  = 12 * 60
BATCH_GAP_MIN         = 30 * 60
BATCH_GAP_MAX         = 50 * 60

# ── Status values ─────────────────────────────────────────────────────────
STATUS_MESSAGED     = "Messaged"
STATUS_NOT_REPLIED  = "Not Replied"
STATUS_REPLIED      = "Replied"
STATUS_NOT_LOOKING  = "Not Looking"

# ── Column names ────────────────────────────────────────────────────────────
COL_NAME        = "Name"
COL_PHONE       = "Contact"
COL_ROLE        = "Role"
COL_STATUS      = "Status"
COL_HR_NOTIFIED = "HR Notified"
COL_MSG1_SENT   = "Msg1 Sent"
COL_MSG2_SENT   = "Msg2 Sent"
COL_MSG3_SENT   = "Msg3 Sent"

# ── Reply Type values ──────────────────────────────────────────────────────
COL_REPLY_TYPE       = "Reply Type"
REPLY_TYPE_POSITIVE  = "Positive"
REPLY_TYPE_NEGATIVE  = "Negative"
REPLY_TYPE_NEUTRAL   = "Neutral"

# ── Grok API (xAI) — for reply classification ───────────────────────────────
# Get your key at: https://console.x.ai/
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_MODEL   = "grok-3-mini"

# ── Daily email report ───────────────────────────────────────────────────────
REPORT_HOUR        = 19
GMAIL_SENDER       = os.environ.get("GMAIL_SENDER",       "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
REPORT_RECIPIENTS  = [r for r in os.environ.get("REPORT_RECIPIENTS", "").split(",") if r]

# ── Telegram Bot ────────────────────────────────────────────────────────────
# Get token from @BotFather. Get chat ID from https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_IDS = [int(x) for x in os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",") if x]
HR_TELEGRAM_IDS      = [int(x) for x in os.environ.get("HR_TELEGRAM_IDS",      "").split(",") if x]

# ── Templates file ──────────────────────────────────────────────────────────
TEMPLATES_FILE = os.path.expanduser("~/whatsapp-automation/templates.txt")

# ── Paths ───────────────────────────────────────────────────────────────────
LOG_DIR    = os.path.expanduser("~/whatsapp-automation/logs")
STATE_FILE = os.path.expanduser("~/whatsapp-automation/state.json")
