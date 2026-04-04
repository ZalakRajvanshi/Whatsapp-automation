"""
One-time script to remove the duplicate columns added by mistake (cols 9-14).
"""
import sheets

ws = sheets.get_worksheet()
raw_headers = ws.row_values(1)
print(f"Current headers: {raw_headers}")

# The duplicate columns we want to remove (added at positions 9-14)
TO_REMOVE = {"Phone", "Message Sent", "Status", "Msg1 Sent At", "Msg2 Sent At", "Msg3 Sent At"}

# Find their column indices (1-based) in reverse order so deletion doesn't shift
cols_to_delete = []
for i, h in enumerate(raw_headers, start=1):
    if h.strip() in TO_REMOVE:
        cols_to_delete.append(i)

# Delete from right to left to keep indices stable
for col in sorted(cols_to_delete, reverse=True):
    print(f"Deleting column {col}: '{raw_headers[col-1]}'")
    ws.delete_columns(col)

print("\nDone. Current headers:")
print(ws.row_values(1))
