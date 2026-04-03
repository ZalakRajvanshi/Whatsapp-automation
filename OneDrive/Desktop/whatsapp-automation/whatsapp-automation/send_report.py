"""
Standalone EOD report sender.

Run manually any time:
    python3 ~/whatsapp-automation/send_report.py

Or let the automation send it automatically at 7 PM daily.
The active campaign tabs are read from state.json (set when the automation last ran).
Falls back to the tabs listed in FALLBACK_TABS if state.json has no active tab.
Only tabs with actual outreach are included — the rest are silently skipped.
One combined email is sent covering all active campaigns.
"""

import json
import os
import sys

# ── Resolve the active tabs ───────────────────────────────────────────────────
STATE_FILE    = os.path.expanduser("~/whatsapp-automation/state.json")
FALLBACK_TABS = []  # Add your sheet tab names here as fallback, e.g. ["Tab1", "Tab2"]

def get_active_tabs() -> list[str]:
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        tabs = state.get("active_tabs", [])
        if tabs:
            return tabs
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return FALLBACK_TABS


# ── Send ─────────────────────────────────────────────────────────────────────
import email_report

tabs = get_active_tabs()
print(f"[Report] Checking {len(tabs)} tab(s): {', '.join(tabs)}")

sent = email_report.send_combined_report(tabs)
sys.exit(0 if sent else 1)
