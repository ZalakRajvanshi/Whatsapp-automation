"""
Telegram Bot — WhatsApp Automation Control Interface

Commands:
  /newcampaign — start a new outreach campaign (guided setup via Telegram)
  /start       — resume automation from state.json
  /stop        — stop the running automation
  /status      — show pipeline summary
  /report      — trigger the EOD email report now
  /logs        — last 25 lines of today's log file
  /help        — list commands

Only TELEGRAM_ALLOWED_IDS in config.py can use this bot.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
    ConversationHandler,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ── Process handle ────────────────────────────────────────────────────────────
_proc = None  # type: subprocess.Popen

# ── Conversation states for /newcampaign ─────────────────────────────────────
ASK_TAB, ASK_ROW, ASK_COUNT, ASK_ROLE, ASK_CONFIRM = range(5)


def _allowed(update: Update) -> bool:
    uid = update.effective_user.id
    allowed = getattr(config, "TELEGRAM_ALLOWED_IDS", [])
    return uid in allowed


async def _deny(update: Update):
    await update.message.reply_text("Not authorised.")


def _is_running() -> bool:
    global _proc
    if _proc and _proc.poll() is None:
        return True
    result = subprocess.run(["pgrep", "-f", "main.py"], capture_output=True)
    return result.returncode == 0


# ── /newcampaign — Step 1: pick tab ──────────────────────────────────────────

async def cmd_newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)

    if _is_running():
        await update.message.reply_text(
            "Automation is already running.\nStop it first with /stop, then start a new campaign."
        )
        return ConversationHandler.END

    await update.message.reply_text("Fetching tabs from sheet...")
    try:
        import sheets
        tabs = sheets.list_tab_names()
    except Exception as e:
        await update.message.reply_text(f"Could not read sheet: {e}")
        return ConversationHandler.END

    if not tabs:
        await update.message.reply_text("No tabs found in the sheet.")
        return ConversationHandler.END

    context.user_data["tabs"] = tabs
    tab_list = "\n".join(f"{i+1}. {t}" for i, t in enumerate(tabs))
    await update.message.reply_text(
        f"*Available tabs:*\n{tab_list}\n\nReply with the tab number:",
        parse_mode="Markdown"
    )
    return ASK_TAB


async def got_tab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tabs = context.user_data.get("tabs", [])
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= len(tabs)):
        await update.message.reply_text(f"Please enter a number between 1 and {len(tabs)}.")
        return ASK_TAB

    chosen = tabs[int(text) - 1]
    context.user_data["tab"] = chosen
    await update.message.reply_text(
        f"Tab: *{chosen}*\n\nStarting row? (e.g. 2 for first data row, 11 to skip first 9)",
        parse_mode="Markdown"
    )
    return ASK_ROW


# ── Step 2: starting row ──────────────────────────────────────────────────────

async def got_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 2:
        await update.message.reply_text("Please enter a row number (minimum 2).")
        return ASK_ROW

    context.user_data["start_row"] = int(text)
    await update.message.reply_text(
        f"Starting from row {text}.\n\nHow many candidates to message today? (1–{config.MAX_DAILY_MESSAGES})"
    )
    return ASK_COUNT


# ── Step 3: count ─────────────────────────────────────────────────────────────

async def got_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= config.MAX_DAILY_MESSAGES):
        await update.message.reply_text(
            f"Please enter a number between 1 and {config.MAX_DAILY_MESSAGES}."
        )
        return ASK_COUNT

    context.user_data["count"] = int(text)
    await update.message.reply_text("What is the role for this campaign?\n(e.g. Product Manager)")
    return ASK_ROLE


# ── Step 4: role ──────────────────────────────────────────────────────────────

async def got_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = update.message.text.strip()
    if not role:
        await update.message.reply_text("Role cannot be empty. Please enter the role.")
        return ASK_ROLE

    context.user_data["role"] = role

    # Fetch candidates preview
    tab       = context.user_data["tab"]
    start_row = context.user_data["start_row"]
    count     = context.user_data["count"]

    await update.message.reply_text("Fetching candidates from sheet...")
    try:
        import sheets
        sheets.ensure_reply_type_column(tab)
        candidates = sheets.get_candidates(tab, start_row, count)
    except Exception as e:
        await update.message.reply_text(f"Could not fetch candidates: {e}")
        return ConversationHandler.END

    if not candidates:
        await update.message.reply_text(
            "No eligible candidates found from that row.\n"
            "Try a different starting row or check the sheet."
        )
        return ConversationHandler.END

    context.user_data["candidates"] = candidates

    # Build preview
    lines = [
        f"*Campaign Summary*",
        f"Tab: {tab}",
        f"Role: {role}",
        f"Starting row: {start_row}",
        f"Candidates found: {len(candidates)} (you asked for {count})",
        "",
        "*First 5 candidates:*",
    ]
    for c in candidates[:5]:
        name  = str(c.get(config.COL_NAME,  "")).strip()
        phone = str(c.get(config.COL_PHONE, "")).strip()
        lines.append(f"  • {name} — {phone}")
    if len(candidates) > 5:
        lines.append(f"  ... and {len(candidates) - 5} more")
    lines.append("")
    lines.append("Type *YES* to start, or /cancel to abort.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    return ASK_CONFIRM


# ── Step 5: confirm ───────────────────────────────────────────────────────────

async def got_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text != "YES":
        await update.message.reply_text("Cancelled. No messages sent.")
        context.user_data.clear()
        return ConversationHandler.END

    tab        = context.user_data["tab"]
    start_row  = context.user_data["start_row"]
    count      = context.user_data["count"]
    role       = context.user_data["role"]

    await update.message.reply_text("Starting campaign...")

    global _proc
    _proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / "main.py"),
            "--campaign",
            f"--tab={tab}",
            f"--row={start_row}",
            f"--count={count}",
            f"--role={role}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path(__file__).parent),
        start_new_session=True,
    )
    await update.message.reply_text(
        f"Campaign started (PID {_proc.pid}) ✅\n"
        f"Tab: {tab} | Role: {role} | {count} candidates from row {start_row}\n\n"
        f"Use /status to track progress."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── /start (resume) ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)

    if _is_running():
        await update.message.reply_text("Automation is already running.")
        return

    if not Path(config.STATE_FILE).exists():
        await update.message.reply_text(
            "No state.json found. Start a new campaign with /newcampaign."
        )
        return

    global _proc
    _proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "main.py"), "--resume"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path(__file__).parent),
        start_new_session=True,
    )
    await update.message.reply_text(
        f"Automation resumed (PID {_proc.pid}) ✅\n"
        f"Resumed from state.json."
    )


# ── /stop ─────────────────────────────────────────────────────────────────────

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)

    global _proc
    stopped = False

    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _proc.kill()
        stopped = True

    result = subprocess.run(["pgrep", "-f", "main.py"], capture_output=True, text=True)
    if result.returncode == 0:
        for pid in result.stdout.strip().split():
            subprocess.run(["kill", pid], capture_output=True)
        stopped = True

    if stopped:
        await update.message.reply_text("Automation stopped ⛔\nUse /start to resume or /newcampaign for a new one.")
    else:
        await update.message.reply_text("Automation was not running.")


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)

    state_path = Path(config.STATE_FILE)
    if not state_path.exists():
        await update.message.reply_text("No state.json — no campaign has run yet.")
        return

    try:
        data = json.loads(state_path.read_text())
    except Exception as e:
        await update.message.reply_text(f"Could not read state.json: {e}")
        return

    total      = len(data)
    replied    = sum(1 for i in data.values() if i.get("replied"))
    msg3_watch = sum(1 for i in data.values() if i.get("msg3_sent_at") and not i.get("replied"))
    msg2_wait  = sum(1 for i in data.values() if i.get("msg2_sent_at") and not i.get("msg3_sent_at") and not i.get("replied"))
    msg1_wait  = sum(1 for i in data.values() if i.get("msg1_sent_at") and not i.get("msg2_sent_at") and not i.get("replied"))
    active     = msg1_wait + msg2_wait + msg3_watch
    done       = replied

    running_str = "Running ✅" if _is_running() else "Stopped ⛔"

    lines = [
        f"*Automation:* {running_str}",
        "",
        f"*Total:* {total} candidates",
        f"🟢 *Active in pipeline:* {active}",
        f"🏁 *Completed:* {done}",
        "",
        f"*Breakdown:*",
        f"  📨 Msg 1 sent, awaiting reply: {msg1_wait}",
        f"  📩 Msg 2 sent, awaiting reply: {msg2_wait}",
        f"  📬 Msg 3 sent, still watching: {msg3_watch}",
        f"  ✅ Replied: {replied}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /report ───────────────────────────────────────────────────────────────────

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)

    state_path = Path(config.STATE_FILE)
    if not state_path.exists():
        await update.message.reply_text("No state.json — nothing to report.")
        return

    await update.message.reply_text("Sending report now...")
    try:
        import email_report
        data = json.loads(state_path.read_text())
        tabs = list({v["tab"] for v in data.values() if v.get("tab")})
        if not tabs:
            await update.message.reply_text("No active tabs in state.json.")
            return
        ok = email_report.send_combined_report(tabs)
        if ok:
            await update.message.reply_text("Report sent ✅")
        else:
            await update.message.reply_text(
                "Report failed — check Gmail credentials in config.py,\n"
                "or no campaigns with classified replies yet."
            )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ── /logs ─────────────────────────────────────────────────────────────────────

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)

    today    = datetime.now().strftime("%Y-%m-%d")
    log_file = Path(config.LOG_DIR) / f"daily_{today}.log"

    if not log_file.exists():
        await update.message.reply_text("No log file for today yet.")
        return

    lines = log_file.read_text(encoding="utf-8").splitlines()
    last  = lines[-25:] if len(lines) > 25 else lines
    text  = "\n".join(last)
    if len(text) > 3800:
        text = text[-3800:]
    await update.message.reply_text(f"```\n{text}\n```", parse_mode="Markdown")


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return await _deny(update)
    await update.message.reply_text(
        "*Available commands*\n\n"
        "/newcampaign — Start a new outreach campaign\n"
        "/start — Resume automation from state.json\n"
        "/stop — Stop the running automation\n"
        "/status — Show pipeline summary\n"
        "/report — Send the EOD email report now\n"
        "/logs — Last 25 lines of today's log\n"
        "/help — Show this message",
        parse_mode="Markdown"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set in config.py — bot cannot start.")
        sys.exit(1)

    allowed = getattr(config, "TELEGRAM_ALLOWED_IDS", [])
    print(f"[Bot] Starting. Allowed IDs: {allowed}")

    app = Application.builder().token(token).build()

    # /newcampaign conversation handler
    campaign_conv = ConversationHandler(
        entry_points=[CommandHandler("newcampaign", cmd_newcampaign)],
        states={
            ASK_TAB:     [MessageHandler(filters.TEXT & ~filters.COMMAND, got_tab)],
            ASK_ROW:     [MessageHandler(filters.TEXT & ~filters.COMMAND, got_row)],
            ASK_COUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_count)],
            ASK_ROLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_role)],
            ASK_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(campaign_conv)
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("logs",   cmd_logs))
    app.add_handler(CommandHandler("help",   cmd_help))

    print("[Bot] Polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
