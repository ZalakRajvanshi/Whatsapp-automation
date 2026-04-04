"""
Google Sheets helper — tab-aware, row-aware.
Uses OAuth2 (credentials.json).
"""

import os
import pickle
from datetime import datetime

import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_HERE      = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(_HERE, "token.pickle")
CREDS_FILE = os.path.join(_HERE, "credentials.json")


# ── Auth ────────────────────────────────────────────────────────────────────

def get_client():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                raise FileNotFoundError(
                    "credentials.json not found. "
                    "Please follow setup instructions to create it."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return gspread.authorize(creds)


def get_spreadsheet():
    return get_client().open_by_key(config.SHEET_ID)


def get_worksheet(tab_name: str):
    return get_spreadsheet().worksheet(tab_name)


# ── Tab helpers ─────────────────────────────────────────────────────────────

def list_tab_names() -> list:
    """Return all tab names in the spreadsheet."""
    return [ws.title for ws in get_spreadsheet().worksheets()]


# ── Column helpers ──────────────────────────────────────────────────────────

def _get_headers(ws) -> list:
    return [h.strip() for h in ws.row_values(1)]


def _ensure_column(ws, headers: list, col_name: str) -> list:
    """Add column header if it doesn't exist. Returns updated headers."""
    if col_name not in headers:
        new_col = len(headers) + 1
        ws.update_cell(1, new_col, col_name)
        headers = _get_headers(ws)
        print(f"[Sheets] Added column '{col_name}'")
    return headers


def _normalize_phone(phone: str) -> str:
    """Keep only digits, take last 10 — normalizes +91XXXXXXXXXX, 91XXXXXXXXXX, XXXXXXXXXX."""
    return ''.join(filter(str.isdigit, str(phone)))[-10:]


def _find_row(ws, headers: list, phone: str):
    """Find 1-based row index for a candidate by phone. Returns row number or None."""
    if config.COL_PHONE not in headers:
        return None
    phone_col   = headers.index(config.COL_PHONE)
    target      = _normalize_phone(phone)
    all_values  = ws.get_all_values()
    for i, row in enumerate(all_values[1:], start=2):
        cell = row[phone_col] if phone_col < len(row) else ""
        if _normalize_phone(cell) == target:
            return i
    return None


def _set_cell(ws, row: int, headers: list, col_name: str, value: str):
    if col_name not in headers:
        return
    col = headers.index(col_name) + 1
    ws.update_cell(row, col, value)
    # Verify the write actually landed
    actual = ws.cell(row, col).value
    if str(actual).strip() != str(value).strip():
        print(f"[Sheets] WARNING: write verify failed — expected '{value}', got '{actual}' (row {row}, col {col_name})")


# ── Candidate fetching ──────────────────────────────────────────────────────

def get_candidates(tab_name: str, start_row: int, count: int) -> list:
    """
    Return up to `count` eligible candidates from `tab_name` starting at `start_row`.

    Eligible = Status is not Replied and not Not Replied (i.e., still in play).
    start_row is the actual spreadsheet row number (header = row 1).
    """
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)

    # Ensure timestamp columns exist (needed for follow-up timing)
    for col in [config.COL_MSG1_SENT, config.COL_MSG2_SENT, config.COL_MSG3_SENT,
                config.COL_HR_NOTIFIED]:
        headers = _ensure_column(ws, headers, col)

    all_values = ws.get_all_values()

    name_col   = headers.index(config.COL_NAME)   if config.COL_NAME   in headers else None
    phone_col  = headers.index(config.COL_PHONE)  if config.COL_PHONE  in headers else None
    status_col = headers.index(config.COL_STATUS) if config.COL_STATUS in headers else None

    if phone_col is None:
        print(f"[Sheets] ERROR: No '{config.COL_PHONE}' column in tab '{tab_name}'")
        return []

    candidates = []
    # start_row is 1-based; row index in all_values is start_row - 1
    for sheet_row in range(start_row, len(all_values) + 1):
        if len(candidates) >= count:
            break
        idx = sheet_row - 1  # 0-based index in all_values
        if idx >= len(all_values):
            break
        row = all_values[idx]

        phone = row[phone_col].strip() if phone_col < len(row) else ""
        if not phone:
            continue

        status = row[status_col].strip() if (status_col is not None and status_col < len(row)) else ""

        # Skip already done candidates
        if status in (config.STATUS_REPLIED, config.STATUS_NOT_REPLIED):
            continue

        name = row[name_col].strip() if (name_col is not None and name_col < len(row)) else ""

        # Collect all header values for this row
        c = {"_sheet_row": sheet_row, "_tab": tab_name}
        for i, h in enumerate(headers):
            c[h] = row[i].strip() if i < len(row) else ""
        candidates.append(c)

    return candidates


def get_followup_candidates(tab_name: str) -> list:
    """
    Return candidates with Status = Messaged (need Msg2 or Msg3 follow-up).
    Includes their Msg1 Sent / Msg2 Sent timestamps.
    """
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    all_values = ws.get_all_values()

    status_col = headers.index(config.COL_STATUS)   if config.COL_STATUS   in headers else None
    phone_col  = headers.index(config.COL_PHONE)    if config.COL_PHONE    in headers else None
    name_col   = headers.index(config.COL_NAME)     if config.COL_NAME     in headers else None
    msg1_col   = headers.index(config.COL_MSG1_SENT) if config.COL_MSG1_SENT in headers else None
    msg2_col   = headers.index(config.COL_MSG2_SENT) if config.COL_MSG2_SENT in headers else None

    result = []
    for sheet_row, row in enumerate(all_values[1:], start=2):
        status = row[status_col].strip() if (status_col is not None and status_col < len(row)) else ""
        if status != config.STATUS_MESSAGED:
            continue
        phone = row[phone_col].strip() if (phone_col is not None and phone_col < len(row)) else ""
        if not phone:
            continue
        c = {
            "_sheet_row": sheet_row,
            "_tab": tab_name,
            config.COL_NAME:      row[name_col].strip()  if (name_col  is not None and name_col  < len(row)) else "",
            config.COL_PHONE:     phone,
            config.COL_STATUS:    status,
            config.COL_MSG1_SENT: row[msg1_col].strip()  if (msg1_col  is not None and msg1_col  < len(row)) else "",
            config.COL_MSG2_SENT: row[msg2_col].strip()  if (msg2_col  is not None and msg2_col  < len(row)) else "",
        }
        result.append(c)
    return result


# ── Status / cell updates ───────────────────────────────────────────────────

def update_status(tab_name: str, phone: str, status: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        print(f"[Sheets] Phone {phone} not found in '{tab_name}'")
        return
    _set_cell(ws, row, headers, config.COL_STATUS, status)
    print(f"[Sheets] {phone}: Status → {status}")


def update_msg1_sent(tab_name: str, phone: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _set_cell(ws, row, headers, config.COL_MSG1_SENT, now)
    _set_cell(ws, row, headers, config.COL_STATUS, config.STATUS_MESSAGED)
    print(f"[Sheets] {phone}: Msg1 sent at {now}, Status → Messaged")


def mark_invalid_number(tab_name: str, phone: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    headers = _ensure_column(ws, headers, config.COL_MSG1_SENT)
    row = _find_row(ws, headers, phone)
    if not row:
        return
    _set_cell(ws, row, headers, config.COL_MSG1_SENT, "WhatsApp number invalid")
    print(f"[Sheets] {phone}: Msg1 → WhatsApp number invalid")


def update_msg2_sent(tab_name: str, phone: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _set_cell(ws, row, headers, config.COL_MSG2_SENT, now)
    print(f"[Sheets] {phone}: Msg2 sent at {now}")


def update_msg3_sent(tab_name: str, phone: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _set_cell(ws, row, headers, config.COL_MSG3_SENT, now)
    _set_cell(ws, row, headers, config.COL_STATUS, config.STATUS_NOT_REPLIED)
    print(f"[Sheets] {phone}: Msg3 sent at {now}, Status → Not Replied")


def mark_replied(tab_name: str, phone: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        return
    _set_cell(ws, row, headers, config.COL_STATUS, config.STATUS_REPLIED)
    print(f"[Sheets] {phone}: Status → Replied")


def mark_hr_notified(tab_name: str, phone: str):
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        return
    _set_cell(ws, row, headers, config.COL_HR_NOTIFIED, "Yes")
    print(f"[Sheets] {phone}: HR Notified → Yes")


def ensure_reply_type_column(tab_name: str):
    """
    Adds a 'Reply Type' column with a Positive/Negative/Neutral dropdown to the
    specified tab — and ONLY that tab. Safe to call on every run: if the column
    already exists it logs and returns immediately without touching anything.

    The dropdown is applied to rows 2–1000 (covers up to 999 candidates).
    strict=False means users can still type freely if needed.
    """
    ws      = get_worksheet(tab_name)
    headers = _get_headers(ws)

    if config.COL_REPLY_TYPE in headers:
        print(f"[Sheets] '{config.COL_REPLY_TYPE}' column already exists in '{tab_name}' — skipping")
        return

    # Add the header cell
    new_col_num = len(headers) + 1          # 1-based column number for gspread
    new_col_idx = len(headers)              # 0-based column index for Sheets API
    ws.update_cell(1, new_col_num, config.COL_REPLY_TYPE)
    print(f"[Sheets] Added '{config.COL_REPLY_TYPE}' column to '{tab_name}' (col {new_col_num})")

    # Apply dropdown validation via the Sheets API batch_update
    # We go through the gspread spreadsheet object which exposes the raw API
    spreadsheet = get_spreadsheet()
    sheet_id    = ws.id   # numeric ID of this specific worksheet/tab

    body = {
        "requests": [
            {
                "setDataValidation": {
                    "range": {
                        "sheetId":          sheet_id,
                        "startRowIndex":    1,              # row 2 (0-indexed, skips header row)
                        "endRowIndex":      1000,           # covers up to 999 data rows
                        "startColumnIndex": new_col_idx,    # 0-based
                        "endColumnIndex":   new_col_idx + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": config.REPLY_TYPE_POSITIVE},
                                {"userEnteredValue": config.REPLY_TYPE_NEGATIVE},
                                {"userEnteredValue": config.REPLY_TYPE_NEUTRAL},
                            ],
                        },
                        "showCustomUi": True,   # renders as a dropdown arrow in the sheet
                        "strict":       False,  # still allows free-text entry if needed
                    },
                }
            }
        ]
    }
    spreadsheet.batch_update(body)
    print(f"[Sheets] Dropdown validation (Positive/Negative/Neutral) applied to '{config.COL_REPLY_TYPE}' in '{tab_name}'")


def get_unclassified_replied(tab_name: str) -> list:
    """
    Returns a list of candidates in tab_name who have Status=Replied
    but an empty Reply Type cell — i.e. they need to be classified.

    Each item: {"name": str, "phone": str, "role": str}
    """
    ws         = get_worksheet(tab_name)
    headers    = _get_headers(ws)
    all_values = ws.get_all_values()

    def col(name):
        return headers.index(name) if name in headers else None

    def cell(row, col_idx):
        if col_idx is None or col_idx >= len(row):
            return ""
        return row[col_idx].strip()

    phone_col  = col(config.COL_PHONE)
    status_col = col(config.COL_STATUS)
    rtype_col  = col(config.COL_REPLY_TYPE)
    name_col   = col(config.COL_NAME)
    role_col   = col(config.COL_ROLE)

    if phone_col is None:
        return []

    result = []
    for row in all_values[1:]:
        phone  = cell(row, phone_col)
        status = cell(row, status_col)
        rtype  = cell(row, rtype_col)
        if phone and status == config.STATUS_REPLIED and not rtype:
            result.append({
                "name":  cell(row, name_col),
                "phone": phone,
                "role":  cell(row, role_col),
            })
    return result


def update_reply_type(tab_name: str, phone: str, reply_type: str):
    """
    Sets the 'Reply Type' cell for a candidate after their reply is classified.
    Called automatically by the monitor worker — HR does not need to fill this manually.

    reply_type must be one of: "Positive", "Negative", "Neutral"
    (defined in config.REPLY_TYPE_* constants)
    """
    ws      = get_worksheet(tab_name)
    headers = _get_headers(ws)
    headers = _ensure_column(ws, headers, config.COL_REPLY_TYPE)  # create column if missing
    row     = _find_row(ws, headers, phone)

    if not row:
        print(f"[Sheets] update_reply_type: phone {phone} not found in '{tab_name}'")
        return

    _set_cell(ws, row, headers, config.COL_REPLY_TYPE, reply_type)
    print(f"[Sheets] {phone}: Reply Type → {reply_type}")


def get_daily_stats(tab_name: str, today_str: str) -> dict:
    """
    Reads the entire tab and computes stats needed for the EOD email report.

    today_str must be "YYYY-MM-DD" — used to identify today's sends by matching
    the start of the stored timestamps (e.g. "2026-03-27 14:30:00" starts with "2026-03-27").

    Returns:
        msg1_sent_today    — int: Msg1 sends with today's date
        msg2_sent_today    — int: Msg2 sends with today's date
        msg3_sent_today    — int: Msg3 sends with today's date
        total_outreach_today — int: sum of the above
        replied_total      — int: all candidates currently with Status=Replied
        reply_type_counts  — dict: {"Positive": n, "Negative": n, "Neutral": n, "": n}
                             "" means replied but Reply Type cell is still blank
        waiting_on_msg1    — int: Status=Messaged, Msg1 sent, no Msg2 yet
        waiting_on_msg2    — int: Status=Messaged, Msg2 sent, no Msg3 yet
        waiting_total      — int: sum of waiting_on_msg1 + waiting_on_msg2
        completed          — int: Status=Not Replied (received all 3 msgs, no reply)
        candidates_today   — list of dicts {name, role, phone, status, reply_type}
                             for every candidate who received any message today
    """
    ws         = get_worksheet(tab_name)
    headers    = _get_headers(ws)
    all_values = ws.get_all_values()

    # Helper: get 0-based column index or None if column missing
    def col(name):
        return headers.index(name) if name in headers else None

    # Helper: safely read a cell value from a row
    def cell(row, col_idx):
        if col_idx is None or col_idx >= len(row):
            return ""
        return row[col_idx].strip()

    name_col   = col(config.COL_NAME)
    phone_col  = col(config.COL_PHONE)
    role_col   = col(config.COL_ROLE)
    status_col = col(config.COL_STATUS)
    msg1_col   = col(config.COL_MSG1_SENT)
    msg2_col   = col(config.COL_MSG2_SENT)
    msg3_col   = col(config.COL_MSG3_SENT)
    rtype_col  = col(config.COL_REPLY_TYPE)

    if phone_col is None:
        print(f"[Sheets] get_daily_stats: no '{config.COL_PHONE}' column in '{tab_name}'")
        return {}

    msg1_today         = 0
    msg2_today         = 0
    msg3_today         = 0
    total_candidates   = 0
    replied_total      = 0
    reply_type_counts  = {
        config.REPLY_TYPE_POSITIVE: 0,
        config.REPLY_TYPE_NEGATIVE: 0,
        config.REPLY_TYPE_NEUTRAL:  0,
        "": 0,   # replied but Reply Type not yet set
    }
    waiting_msg1      = 0
    waiting_msg2      = 0
    completed         = 0
    candidates_today  = []
    replied_candidates = []   # all replied candidates with name, role, reply_type

    for row in all_values[1:]:   # skip header row
        phone = cell(row, phone_col)
        if not phone:
            continue

        total_candidates += 1
        status    = cell(row, status_col)
        msg1_sent = cell(row, msg1_col)
        msg2_sent = cell(row, msg2_col)
        msg3_sent = cell(row, msg3_col)
        rtype     = cell(row, rtype_col)
        name      = cell(row, name_col)
        role      = cell(row, role_col)

        # ── Today's outreach ─────────────────────────────────────────────────
        # Timestamps are stored as "YYYY-MM-DD HH:MM:SS" — startswith() is enough
        sent_today = False
        if msg1_sent.startswith(today_str):
            msg1_today += 1
            sent_today  = True
        if msg2_sent.startswith(today_str):
            msg2_today += 1
            sent_today  = True
        if msg3_sent.startswith(today_str):
            msg3_today += 1
            sent_today  = True

        # Build the "profiles reached today" list for the email body
        if sent_today:
            candidates_today.append({
                "name":       name,
                "role":       role,
                "phone":      phone,
                "status":     status,
                "reply_type": rtype,
            })

        # ── Reply counts (all-time, reflects current sheet state) ─────────────
        if status == config.STATUS_REPLIED:
            replied_total += 1
            # Use "" bucket for blank/unrecognised reply types
            key = rtype if rtype in reply_type_counts else ""
            reply_type_counts[key] += 1
            # Track individual replied candidates for the email name listing
            replied_candidates.append({
                "name":       name,
                "role":       role,
                "phone":      phone,
                "reply_type": rtype if rtype else "Unclassified",
            })

        # ── Still waiting breakdown ───────────────────────────────────────────
        if status == config.STATUS_MESSAGED:
            if msg2_sent:
                waiting_msg2 += 1   # received Msg2, waiting for Msg3 or reply
            else:
                waiting_msg1 += 1   # received Msg1 only, waiting for Msg2 or reply

        # ── Completed (no reply after all 3 messages) ─────────────────────────
        if status == config.STATUS_NOT_REPLIED:
            completed += 1

    return {
        "total_candidates":     total_candidates,
        "msg1_sent_today":      msg1_today,
        "msg2_sent_today":      msg2_today,
        "msg3_sent_today":      msg3_today,
        "total_outreach_today": msg1_today + msg2_today + msg3_today,
        "replied_total":        replied_total,
        "reply_type_counts":    reply_type_counts,
        "replied_candidates":   replied_candidates,   # list of {name, role, phone, reply_type}
        "waiting_on_msg1":      waiting_msg1,
        "waiting_on_msg2":      waiting_msg2,
        "waiting_total":        waiting_msg1 + waiting_msg2,
        "completed":            completed,
        "candidates_today":     candidates_today,
    }


def get_candidate_status(tab_name: str, phone: str) -> dict:
    """Get current sheet state for one candidate."""
    ws = get_worksheet(tab_name)
    headers = _get_headers(ws)
    row = _find_row(ws, headers, phone)
    if not row:
        return {"status": "", "hr_notified": "", "msg1_sent": "", "msg2_sent": ""}
    row_data = ws.row_values(row)

    def _get(col):
        if col in headers:
            idx = headers.index(col)
            return row_data[idx].strip() if idx < len(row_data) else ""
        return ""

    return {
        "status":       _get(config.COL_STATUS),
        "hr_notified":  _get(config.COL_HR_NOTIFIED),
        "msg1_sent":    _get(config.COL_MSG1_SENT),
        "msg2_sent":    _get(config.COL_MSG2_SENT),
    }
