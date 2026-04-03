"""
One-time setup script to add required columns to the Google Sheet
and verify the structure is correct.

Run this ONCE after setting up credentials.json:
  python3 setup_sheets.py
"""

import sheets
import config


REQUIRED_COLUMNS = [
    config.COL_NAME,
    config.COL_PHONE,
    config.COL_ROLE,
    config.COL_MESSAGE_SENT,
    config.COL_REPLY,
    config.COL_STATUS,
    config.COL_MSG1_TIME,
    config.COL_MSG2_TIME,
    config.COL_MSG3_TIME,
]


def setup():
    print("[Setup] Connecting to Google Sheet...")
    ws = sheets.get_worksheet()
    existing_headers = ws.row_values(1)
    print(f"[Setup] Current columns: {existing_headers}")

    missing = [col for col in REQUIRED_COLUMNS if col not in existing_headers]
    if missing:
        print(f"\n[Setup] Adding missing columns: {missing}")
        next_col = len(existing_headers) + 1
        for col_name in missing:
            ws.update_cell(1, next_col, col_name)
            print(f"  Added column: {col_name} (column {next_col})")
            next_col += 1
    else:
        print("[Setup] ✓ All required columns present")

    # Show current data
    print("\n[Setup] Current candidates in sheet:")
    candidates = sheets.get_all_candidates()
    sheets.print_candidates_table(candidates)

    new_count = len([c for c in candidates if str(c.get(config.COL_STATUS, "")).strip().lower() == "new"])
    print(f"[Setup] ✓ Ready to run. {new_count} candidate(s) with Status=New")


if __name__ == "__main__":
    setup()
