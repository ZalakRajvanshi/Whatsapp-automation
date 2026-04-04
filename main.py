"""
WhatsApp Recruitment Outreach Automation — Queue-Based Single-Sender Architecture

One rule: ONLY the sender_worker thread ever calls whatsapp.send_message().

Architecture:
  send_queue     — all outgoing messages queued here (msg1/msg2/msg3)
  sender_worker  — drains queue, 5–12 min within-batch gap, 30–50 min between batches
                   respects 30/day budget; defers remainder to tomorrow if limit hit
  monitor_worker — checks replies every 10 min, queues follow-ups when due (never sends directly)
  report_worker  — sends 7 PM EOD email

HR notifications go via Telegram (not WhatsApp) — zero budget cost.

Usage:
  python3 main.py              — interactive startup flow
  python3 main.py --resume     — resume from state.json (monitor only)
  python3 main.py --campaign   -- launched by Telegram bot with args
  python3 main.py --setup      — test Google Sheets connection only
"""

import json
import logging
import os
import queue
import random
import requests
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import classifier
import config
import email_report
import sheets
import whatsapp

# ── Logging ──────────────────────────────────────────────────────────────────

def _setup_logging():
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    today    = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"daily_{today}.log"

    logger = logging.getLogger("wa_automation")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(sh)
        logger.addHandler(fh)
    return logger


log = _setup_logging()

# ── Shared state ──────────────────────────────────────────────────────────────
# Per-phone pipeline schema:
# {
#   "name":         str,
#   "role":         str,
#   "tab":          str,
#   "msg1_sent_at": float | None,
#   "msg2_sent_at": float | None,
#   "msg3_sent_at": float | None,
#   "msg2_queued":  bool,   # True once Msg2 is in send_queue (avoids double-queue)
#   "msg3_queued":  bool,
#   "replied":      bool,
#   "hr_notified":  bool,
#   "baseline":     list[str],
# }

pipeline   = {}
state_lock = threading.Lock()

# Deferred items: queue items that couldn't go out today (budget hit / quiet hours).
# Saved to state.json under "_deferred" and reloaded on next run.
# Each item: {"type", "phone", "name", "role", "tab", "message"}
deferred      = []
deferred_lock = threading.Lock()

# ── Send queue ────────────────────────────────────────────────────────────────
# Each item dict:
#   type    : "msg1" | "msg2" | "msg3"
#   phone   : str
#   name    : str
#   role    : str
#   tab     : str
#   message : str

send_queue = queue.Queue()

# ── State persistence ─────────────────────────────────────────────────────────

def _save_state():
    try:
        data = {}
        for phone, info in pipeline.items():
            data[phone] = {
                "name":         info["name"],
                "role":         info["role"],
                "tab":          info["tab"],
                "msg1_sent_at": info["msg1_sent_at"],
                "msg2_sent_at": info["msg2_sent_at"],
                "msg3_sent_at": info["msg3_sent_at"],
                "msg2_queued":  info.get("msg2_queued", False),
                "msg3_queued":  info.get("msg3_queued", False),
                "replied":      info["replied"],
                "hr_notified":  info["hr_notified"],
                "baseline":     info.get("baseline", []),
            }
        with deferred_lock:
            data["_deferred"] = list(deferred)

        Path(config.STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(config.STATE_FILE).write_text(json.dumps(data, indent=2))
    except Exception as e:
        log.warning(f"Could not save state.json: {e}")


def _load_state():
    if not os.path.exists(config.STATE_FILE):
        return
    try:
        data = json.loads(Path(config.STATE_FILE).read_text())
        with state_lock:
            for phone, info in data.items():
                if phone.startswith("_"):
                    continue  # skip meta keys
                if phone not in pipeline:
                    pipeline[phone] = {
                        "name":         info.get("name", ""),
                        "role":         info.get("role", ""),
                        "tab":          info.get("tab", ""),
                        "msg1_sent_at": info.get("msg1_sent_at"),
                        "msg2_sent_at": info.get("msg2_sent_at"),
                        "msg3_sent_at": info.get("msg3_sent_at"),
                        "msg2_queued":  info.get("msg2_queued", False),
                        "msg3_queued":  info.get("msg3_queued", False),
                        "replied":      info.get("replied", False),
                        "hr_notified":  info.get("hr_notified", False),
                        "baseline":     info.get("baseline", []),
                    }
        with deferred_lock:
            saved = data.get("_deferred", [])
            deferred.clear()
            deferred.extend(saved)
        log.info(f"Resumed {len(pipeline)} candidate(s) from state.json "
                 f"({len(deferred)} deferred item(s))")
    except Exception as e:
        log.warning(f"Could not load state.json: {e}")


# ── Templates ─────────────────────────────────────────────────────────────────

def load_templates() -> dict:
    path = Path(config.TEMPLATES_FILE)
    if not path.exists():
        raise FileNotFoundError(f"templates.txt not found at {config.TEMPLATES_FILE}")

    templates     = {}
    current_key   = None
    current_lines = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("[") and line.endswith("]"):
            if current_key:
                templates[current_key] = "\n".join(current_lines).strip()
            current_key   = line[1:-1]
            current_lines = []
        else:
            current_lines.append(line)

    if current_key:
        templates[current_key] = "\n".join(current_lines).strip()

    return templates


# ── Anti-ban / daily budget ───────────────────────────────────────────────────

_daily_count = 0
_daily_date  = None
_daily_lock  = threading.Lock()


def _can_send():
    global _daily_count, _daily_date
    with _daily_lock:
        now = datetime.now()
        if _daily_date != now.date():
            _daily_count = 0
            _daily_date  = now.date()
        if now.weekday() == 6:
            return False, "Sunday (no sends on Sundays)"
        hour = now.hour
        if hour >= config.QUIET_HOUR_START or hour < config.QUIET_HOUR_END:
            return False, f"Quiet hours ({config.QUIET_HOUR_START}:00–{config.QUIET_HOUR_END}:00)"
        if _daily_count >= config.MAX_DAILY_MESSAGES:
            return False, f"Daily limit reached ({config.MAX_DAILY_MESSAGES} messages)"
        return True, ""


def _record_send():
    global _daily_count
    with _daily_lock:
        _daily_count += 1


def _budget_remaining():
    with _daily_lock:
        now = datetime.now()
        if _daily_date != now.date():
            return config.MAX_DAILY_MESSAGES
        return max(0, config.MAX_DAILY_MESSAGES - _daily_count)


# ── Pipeline helpers ──────────────────────────────────────────────────────────

def _pipeline_summary():
    with state_lock:
        replied = sum(1 for i in pipeline.values() if i["replied"])
        msg3    = sum(1 for i in pipeline.values() if i["msg3_sent_at"] and not i["replied"])
        pending = len(pipeline) - replied - msg3
    with deferred_lock:
        ndep = len(deferred)
    dep_str = f" | Deferred tomorrow: {ndep}" if ndep else ""
    return f"Replied: {replied} | Msg3 sent: {msg3} | Still pending: {pending}{dep_str}"


def _is_pipeline_done():
    with state_lock:
        if not pipeline:
            return False
        return all(
            info["replied"] or info["msg3_sent_at"] is not None
            for info in pipeline.values()
        )


# ── Working-hours scheduler ───────────────────────────────────────────────────

def _snap_to_work_hours(earliest_ts: float) -> float:
    dt = datetime.fromtimestamp(earliest_ts)
    for _ in range(14):
        if dt.weekday() == 6:
            dt = (dt + timedelta(days=1)).replace(
                hour=config.WORK_HOUR_START, minute=0, second=0, microsecond=0
            )
            continue
        if dt.hour < config.WORK_HOUR_START:
            dt = dt.replace(hour=config.WORK_HOUR_START, minute=0, second=0, microsecond=0)
        elif dt.hour >= config.WORK_HOUR_END:
            dt = (dt + timedelta(days=1)).replace(
                hour=config.WORK_HOUR_START, minute=0, second=0, microsecond=0
            )
            continue
        break
    return dt.timestamp()


# ── Smart sleep (monitor) ─────────────────────────────────────────────────────

def _next_wake_secs():
    now  = time.time()
    wake = config.MONITOR_INTERVAL

    with state_lock:
        for info in pipeline.values():
            if info["replied"] or info["msg3_sent_at"]:
                continue
            if info["msg1_sent_at"] and not info["msg2_sent_at"]:
                send_at = _snap_to_work_hours(info["msg1_sent_at"] + config.SEND_DELAY)
                wake    = min(wake, send_at - now)
            elif info["msg2_sent_at"] and not info["msg3_sent_at"]:
                send_at = _snap_to_work_hours(info["msg2_sent_at"] + config.SEND_DELAY)
                wake    = min(wake, send_at - now)

    return max(wake, 30)


# ── HR Notifications via Telegram ─────────────────────────────────────────────

def _notify_hr_telegram(name: str, role: str, phone: str, messages: str) -> bool:
    """Send HR reply notification via Telegram instead of WhatsApp. Zero budget cost."""
    token  = getattr(config, "TELEGRAM_BOT_TOKEN", "")
    hr_ids = getattr(config, "HR_TELEGRAM_IDS", [])

    if not token or not hr_ids:
        log.warning("[HR] TELEGRAM_BOT_TOKEN or HR_TELEGRAM_IDS not set — skipping Telegram notify")
        return False

    text = (
        f"*New Reply* from *{name}*\n"
        f"Role: {role}\n"
        f"Phone: {phone}\n\n"
        f"Message:\n{messages}"
    )

    success = True
    for chat_id in hr_ids:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            if not r.ok:
                log.warning(f"[HR] Telegram notify failed for chat_id {chat_id}: {r.text}")
                success = False
        except Exception as e:
            log.warning(f"[HR] Telegram notify error: {e}")
            success = False

    return success


# ── Classify existing unclassified replies ────────────────────────────────────

def classify_existing_replies(tab: str):
    unclassified = sheets.get_unclassified_replied(tab)
    if not unclassified:
        log.info(f"[Classify] No unclassified replies in '{tab}'.")
        return

    log.info(f"[Classify] {len(unclassified)} unclassified replied candidate(s) in '{tab}'...")

    for c in unclassified:
        phone = c["phone"]
        name  = c["name"]

        with whatsapp.driver_lock:
            msgs = whatsapp.get_all_incoming_messages(phone)

        if not msgs:
            log.info(f"[Classify] {name}: no messages found — skipping")
            continue

        reply_text = " ".join(msgs[-5:])
        reply_type = classifier.classify_reply(reply_text)
        sheets.update_reply_type(tab, phone, reply_type)
        log.info(f"[Classify] {name} → {reply_type}")
        time.sleep(random.uniform(4, 8))

    log.info(f"[Classify] Done for '{tab}'.")


# ── WORKER 3: Report ──────────────────────────────────────────────────────────

def report_worker():
    now    = datetime.now()
    target = now.replace(hour=config.REPORT_HOUR, minute=0, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)

    wait = (target - now).total_seconds()
    log.info(f"[Report] Scheduled for {target.strftime('%H:%M')} — sleeping {wait/3600:.1f}h")
    time.sleep(wait)

    tabs = list({info["tab"] for info in pipeline.values() if info.get("tab")})
    if not tabs:
        log.info("[Report] No active tabs in pipeline — skipping report.")
        return

    with deferred_lock:
        dep_snapshot = list(deferred)

    log.info(f"[Report] Sending combined EOD report for {len(tabs)} tab(s)...")
    email_report.send_combined_report(tabs, deferred_items=dep_snapshot)


# ── WORKER 1: Sender ──────────────────────────────────────────────────────────

def sender_worker(monitor_done_event):
    """
    The ONLY thread that sends WhatsApp messages.

    Gaps:
      - Within same batch type (e.g., all msg1): 5–12 min between sends
      - Switching batch type (msg1→msg2, msg2→msg3): 30–50 min gap

    Budget: stops and defers remaining queue items when daily limit is hit.
    """
    log.info("[Sender] Started — waiting for items in send_queue...")

    last_type      = None
    last_send_time = 0.0

    while True:
        # Pull next item (block up to 30s, then check if we should exit)
        try:
            item = send_queue.get(timeout=30)
        except queue.Empty:
            if monitor_done_event.is_set() and send_queue.empty():
                log.info("[Sender] Queue empty and monitor done — exiting.")
                break
            continue

        msg_type = item["type"]
        phone    = item["phone"]
        name     = item["name"]
        tab      = item["tab"]
        message  = item["message"]

        now = time.time()

        # ── Gap calculation ─────────────────────────────────────────────────
        if last_send_time > 0:
            if last_type != msg_type:
                # Batch transition: 30–50 min gap
                gap     = random.uniform(config.BATCH_GAP_MIN, config.BATCH_GAP_MAX)
                elapsed = now - last_send_time
                if elapsed < gap:
                    wait = gap - elapsed
                    log.info(
                        f"[Sender] Batch gap ({last_type} → {msg_type}) — "
                        f"waiting {wait/60:.0f} min..."
                    )
                    time.sleep(wait)
            else:
                # Within-batch gap: 5–12 min
                gap     = random.uniform(config.WITHIN_BATCH_GAP_MIN, config.WITHIN_BATCH_GAP_MAX)
                elapsed = now - last_send_time
                if elapsed < gap:
                    wait = gap - elapsed
                    log.info(f"[Sender] Next send ({msg_type}) in {wait/60:.0f} min...")
                    time.sleep(wait)

        # ── Budget check ────────────────────────────────────────────────────
        ok, reason = _can_send()
        if not ok:
            log.warning(f"[Sender] {reason} — deferring this and remaining queue items")
            with deferred_lock:
                deferred.append(item)
                while not send_queue.empty():
                    try:
                        deferred.append(send_queue.get_nowait())
                    except queue.Empty:
                        break
            _save_state()
            log.info(f"[Sender] {len(deferred)} item(s) deferred to tomorrow.")
            break

        # ── Send ────────────────────────────────────────────────────────────
        log.info(f"[Sender] Sending {msg_type} → {name} ({phone})")

        if msg_type == "msg1":
            # Take baseline atomically with send so we catch exactly pre-send messages
            with whatsapp.driver_lock:
                baseline = whatsapp.get_all_incoming_messages(phone)
                log.info(f"[Sender] {name}: baseline = {len(baseline)} existing message(s)")
                t0      = time.time()
                success = whatsapp.send_message(phone, message)
                elapsed = time.time() - t0
        else:
            with whatsapp.driver_lock:
                t0      = time.time()
                success = whatsapp.send_message(phone, message)
                elapsed = time.time() - t0
            baseline = None

        if success:
            _record_send()
            sent_at        = time.time()
            last_type      = msg_type
            last_send_time = sent_at

            with state_lock:
                if msg_type == "msg1":
                    pipeline[phone] = {
                        "name":         name,
                        "role":         item["role"],
                        "tab":          tab,
                        "msg1_sent_at": sent_at,
                        "msg2_sent_at": None,
                        "msg3_sent_at": None,
                        "msg2_queued":  False,
                        "msg3_queued":  False,
                        "replied":      False,
                        "hr_notified":  False,
                        "baseline":     baseline or [],
                    }
                elif msg_type == "msg2":
                    if phone in pipeline:
                        pipeline[phone]["msg2_sent_at"] = sent_at
                elif msg_type == "msg3":
                    if phone in pipeline:
                        pipeline[phone]["msg3_sent_at"] = sent_at
                _save_state()

            if msg_type == "msg1":
                sheets.update_msg1_sent(tab, phone)
                log.info(f"[Sender] ✓ Msg1 sent to {name} in {elapsed:.1f}s")
            elif msg_type == "msg2":
                sheets.update_msg2_sent(tab, phone)
                log.info(f"[Sender] ✓ Msg2 sent to {name} in {elapsed:.1f}s")
            elif msg_type == "msg3":
                sheets.update_msg3_sent(tab, phone)
                sheets.update_status(tab, phone, config.STATUS_NOT_REPLIED)
                log.info(f"[Sender] ✓ Msg3 sent to {name} in {elapsed:.1f}s — Status → Not Replied")
        else:
            log.error(f"[Sender] ✗ Failed to send {msg_type} to {name}")
            if msg_type == "msg1":
                sheets.mark_invalid_number(tab, phone)

        send_queue.task_done()

    remaining = _budget_remaining()
    log.info(f"[Sender] Done. Budget remaining today: {remaining}/{config.MAX_DAILY_MESSAGES}")


# ── WORKER 2: Monitor ─────────────────────────────────────────────────────────

def monitor_worker(templates: dict, monitor_done_event):
    """
    Checks replies and queues follow-ups. Never sends directly.
    Sets monitor_done_event when all candidates are fully processed.
    """
    REPLY_WATCH_WINDOW = 7 * 24 * 3600

    log.info(f"[Monitor] Starting — reply checks every {config.MONITOR_INTERVAL // 60} min | "
             f"follow-ups queued at {config.SEND_DELAY // 3600}h mark")

    while True:
        wait = _next_wake_secs()
        log.info(f"[Monitor] Next check in {wait:.0f}s ({wait/3600:.1f}h)...")
        time.sleep(wait)

        with state_lock:
            to_check = {
                p: dict(info) for p, info in pipeline.items()
                if info.get("msg1_sent_at") is not None
            }

        if not to_check:
            log.info("[Monitor] No candidates with Msg1 sent yet — waiting...")
            continue

        now = time.time()
        log.info(f"[Monitor] Checking {len(to_check)} candidate(s)...")

        # ── Step 1: Check replies ─────────────────────────────────────────
        for phone, snap in to_check.items():
            if snap["replied"]:
                continue

            # 7-day watch window
            last_sent = (snap.get("msg3_sent_at") or snap.get("msg2_sent_at")
                         or snap.get("msg1_sent_at"))
            if last_sent and (now - last_sent) > REPLY_WATCH_WINDOW:
                log.info(f"[Monitor] {snap['name']} — 7 days since last msg, marking Not Replied")
                with state_lock:
                    if phone in pipeline:
                        pipeline[phone]["replied"] = True
                        _save_state()
                sheets.update_status(snap["tab"], phone, config.STATUS_NOT_REPLIED)
                continue

            log.info(f"[Monitor] Checking reply for {snap['name']}...")
            with whatsapp.driver_lock:
                new_msgs = whatsapp.get_new_replies(phone, snap.get("baseline", []))

            if new_msgs:
                log.info(f"[Monitor] Reply from {snap['name']}: {new_msgs}")
                sheets.mark_replied(snap["tab"], phone)

                reply_text = " ".join(new_msgs)
                reply_type = classifier.classify_reply(reply_text)
                sheets.update_reply_type(snap["tab"], phone, reply_type)
                log.info(f"[Monitor] Reply type → {reply_type} for {snap['name']}")

                if reply_type == config.REPLY_TYPE_NEGATIVE:
                    sheets.update_status(snap["tab"], phone, config.STATUS_NOT_LOOKING)
                    log.info(f"[Monitor] {snap['name']} marked Not Looking")

                # HR notify via Telegram (no WhatsApp message, no budget cost)
                hr_ok = False
                if not snap["hr_notified"]:
                    hr_ok = _notify_hr_telegram(
                        snap["name"], snap["role"], phone, "\n".join(new_msgs)
                    )
                    if hr_ok:
                        sheets.mark_hr_notified(snap["tab"], phone)
                        log.info(f"[Monitor] HR notified (Telegram) for {snap['name']}")
                    else:
                        log.warning(f"[Monitor] HR Telegram notify failed for {snap['name']} — will retry next cycle")

                with state_lock:
                    if phone in pipeline:
                        pipeline[phone]["replied"]     = True
                        pipeline[phone]["hr_notified"] = hr_ok or snap["hr_notified"]
                        _save_state()
            else:
                log.info(f"[Monitor] No reply from {snap['name']}")

            time.sleep(random.uniform(3, 6))

        # ── Step 2: Queue follow-ups when due ────────────────────────────
        now = time.time()
        with state_lock:
            to_followup = {
                p: dict(info) for p, info in pipeline.items()
                if not info["replied"] and info.get("msg1_sent_at")
            }

        for phone, snap in to_followup.items():
            name = snap["name"]
            tab  = snap["tab"]
            role = snap["role"]

            # ── Msg2 ──────────────────────────────────────────────────────
            if snap["msg2_sent_at"] is None and not snap.get("msg2_queued"):
                send_at = _snap_to_work_hours(snap["msg1_sent_at"] + config.SEND_DELAY)
                if now < send_at:
                    hrs_left  = (send_at - now) / 3600
                    send_time = datetime.fromtimestamp(send_at).strftime("%a %b %d %H:%M")
                    log.info(f"[Monitor] {name}: Msg2 scheduled for {send_time} (~{hrs_left:.1f}h)")
                    continue

                # Cross-check sheet
                status = sheets.get_candidate_status(tab, phone)
                if status["status"] == config.STATUS_REPLIED:
                    log.info(f"[Monitor] {name} already replied (sheet) — skipping Msg2")
                    with state_lock:
                        if phone in pipeline:
                            pipeline[phone]["replied"] = True
                            _save_state()
                    continue

                msg2 = templates["MSG2"].format(name=name, role=role)
                send_queue.put({
                    "type": "msg2", "phone": phone, "name": name,
                    "role": role, "tab": tab, "message": msg2,
                })
                with state_lock:
                    if phone in pipeline:
                        pipeline[phone]["msg2_queued"] = True
                        _save_state()
                log.info(f"[Monitor] Queued Msg2 for {name}")

            # ── Msg3 ──────────────────────────────────────────────────────
            elif (snap["msg2_sent_at"] is not None
                  and snap["msg3_sent_at"] is None
                  and not snap.get("msg3_queued")):

                send_at = _snap_to_work_hours(snap["msg2_sent_at"] + config.SEND_DELAY)
                if now < send_at:
                    hrs_left  = (send_at - now) / 3600
                    send_time = datetime.fromtimestamp(send_at).strftime("%a %b %d %H:%M")
                    log.info(f"[Monitor] {name}: Msg3 scheduled for {send_time} (~{hrs_left:.1f}h)")
                    continue

                status = sheets.get_candidate_status(tab, phone)
                if status["status"] == config.STATUS_REPLIED:
                    log.info(f"[Monitor] {name} already replied (sheet) — skipping Msg3")
                    with state_lock:
                        if phone in pipeline:
                            pipeline[phone]["replied"] = True
                            _save_state()
                    continue

                msg3 = templates["MSG3"].format(name=name, role=role)
                send_queue.put({
                    "type": "msg3", "phone": phone, "name": name,
                    "role": role, "tab": tab, "message": msg3,
                })
                with state_lock:
                    if phone in pipeline:
                        pipeline[phone]["msg3_queued"] = True
                        _save_state()
                log.info(f"[Monitor] Queued Msg3 for {name}")

        # ── Summary ───────────────────────────────────────────────────────
        log.info(f"[Monitor] Status — {_pipeline_summary()}")

        if _is_pipeline_done() and send_queue.empty():
            with state_lock:
                still_watching = [
                    p for p, info in pipeline.items()
                    if info.get("msg3_sent_at") and not info["replied"]
                ]
            if not still_watching:
                log.info("=" * 60)
                log.info("  ALL DONE — AUTOMATION COMPLETE")
                log.info("=" * 60)
                log.info(_pipeline_summary())
                log.info(f"  Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                log.info("=" * 60)
                monitor_done_event.set()
                break
            else:
                log.info(
                    f"[Monitor] Sequences complete — still watching "
                    f"{len(still_watching)} candidate(s) for reply after Msg3."
                )


# ── Startup flow (interactive) ────────────────────────────────────────────────

def _pick_tab() -> str:
    print("\nAvailable tabs in the sheet:")
    tab_names = sheets.list_tab_names()
    for i, name in enumerate(tab_names, 1):
        print(f"   {i}. {name}")
    while True:
        choice = input("\nEnter tab number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(tab_names):
            return tab_names[int(choice) - 1]
        print("   Please enter a valid number.")


def _ask_int(prompt: str, min_val: int, max_val: int) -> int:
    while True:
        val = input(prompt).strip()
        if val.isdigit() and min_val <= int(val) <= max_val:
            return int(val)
        print(f"   Please enter a number between {min_val} and {max_val}.")


def _show_preview(candidates: list, role: str, templates: dict):
    print("\n" + "=" * 72)
    print("  CANDIDATES SELECTED FOR TODAY")
    print("=" * 72)
    print(f"  {'#':<4} {'Name':<22} {'Phone':<16} {'Current Status':<16}")
    print("-" * 72)
    for i, c in enumerate(candidates, 1):
        name   = str(c.get(config.COL_NAME,   "")).strip()
        phone  = str(c.get(config.COL_PHONE,  "")).strip()
        status = str(c.get(config.COL_STATUS, "")).strip() or "(blank)"
        print(f"  {i:<4} {name:<22} {phone:<16} {status:<16}")
    print("=" * 72)
    print(f"\n  Role        : {role}")
    print(f"  Within-batch gap : {config.WITHIN_BATCH_GAP_MIN//60}–{config.WITHIN_BATCH_GAP_MAX//60} min between messages")
    print(f"  Batch gap        : {config.BATCH_GAP_MIN//60}–{config.BATCH_GAP_MAX//60} min between Msg1/Msg2/Msg3 batches")
    print(f"  Max/day          : {config.MAX_DAILY_MESSAGES} messages total")
    print(f"  HR notifications : Telegram (no WhatsApp budget used)")
    print("\n  Message 1 preview:")
    sample_full = str(candidates[0].get(config.COL_NAME, "")).strip() if candidates else "Candidate"
    sample_name = sample_full.split()[0] if sample_full else "Candidate"
    preview = templates["MSG1"].format(name=sample_name, role=role)
    for line in preview.splitlines():
        print(f"    {line}")
    print()


def startup_flow():
    print("\n" + "=" * 60)
    print("  WhatsApp Outreach — Campaign Setup")
    print("=" * 60)

    try:
        templates = load_templates()
    except FileNotFoundError as e:
        print(f"\n{e}")
        return None, None, None, None

    for key in ("MSG2", "MSG3"):
        if templates.get(key, "").startswith("(Add your"):
            print(f"\nWARNING: {key} in templates.txt is still empty.")

    tab = _pick_tab()
    print(f"   Selected: {tab}")
    sheets.ensure_reply_type_column(tab)

    start_row = _ask_int(
        "\nEnter the starting row number (e.g. 2 for first data row): ", 2, 10000
    )
    count = _ask_int(
        f"How many candidates to message today? (1–{config.MAX_DAILY_MESSAGES}): ",
        1, config.MAX_DAILY_MESSAGES
    )
    role = input("What is the role for this campaign? (e.g. Product Manager): ").strip()
    if not role:
        print("   Role cannot be empty.")
        return None, None, None, None

    print(f"\n   Fetching up to {count} eligible candidates from row {start_row} in '{tab}'...")
    try:
        candidates = sheets.get_candidates(tab, start_row, count)
    except Exception as e:
        print(f"\nCould not read the sheet: {e}")
        return None, None, None, None

    if not candidates:
        print("\nNo eligible candidates found from that row.")
        return None, None, None, None

    if len(candidates) < count:
        print(f"\nOnly {len(candidates)} eligible candidate(s) found (you asked for {count}).")

    _show_preview(candidates, role, templates)
    confirm = input("Type YES to start sending, or anything else to cancel: ").strip()
    if confirm != "YES":
        print("\n   Cancelled.")
        return None, None, None, None

    return candidates, role, tab, templates


# ── Queue helpers ─────────────────────────────────────────────────────────────

def _queue_msg1_batch(candidates: list, role: str, templates: dict):
    """Add all Msg1 sends to the queue. Called once at campaign start."""
    for c in candidates:
        full_name = str(c.get(config.COL_NAME,  "")).strip()
        name      = full_name.split()[0] if full_name else ""
        phone     = str(c.get(config.COL_PHONE, "")).strip()
        tab       = c.get("_tab", "")
        if not phone:
            log.warning(f"[Queue] Skipping {full_name} — no phone number")
            continue
        message = templates["MSG1"].format(name=name, role=role)
        send_queue.put({
            "type": "msg1", "phone": phone, "name": name,
            "role": role, "tab": tab, "message": message,
        })
    log.info(f"[Queue] {send_queue.qsize()} Msg1 item(s) queued")


def _requeue_deferred():
    """Re-add yesterday's deferred items to the send queue (called on resume/start)."""
    with deferred_lock:
        items = list(deferred)
        deferred.clear()
    if items:
        for item in items:
            send_queue.put(item)
        log.info(f"[Queue] {len(items)} deferred item(s) re-queued from yesterday")
    return len(items)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "--setup" in args:
        log.info("Testing Google Sheets connection...")
        try:
            sheets.get_client()
            log.info("Auth OK")
            tabs = sheets.list_tab_names()
            log.info(f"Sheet accessible — {len(tabs)} tabs: {tabs}")
        except Exception as e:
            log.error(f"Error: {e}")
        return

    # ── Campaign mode (launched by Telegram bot) ──────────────────────────────
    if "--campaign" in args:
        def _get_arg(prefix):
            for a in args:
                if a.startswith(prefix):
                    return a[len(prefix):]
            return None

        tab       = _get_arg("--tab=")
        row_str   = _get_arg("--row=")
        count_str = _get_arg("--count=")
        role      = _get_arg("--role=")

        if not all([tab, row_str, count_str, role]):
            log.error("--campaign requires --tab= --row= --count= --role=")
            return

        start_row = int(row_str)
        count     = int(count_str)

        try:
            templates = load_templates()
        except FileNotFoundError as e:
            log.error(str(e))
            return

        _load_state()

        log.info("Opening WhatsApp Web...")
        with whatsapp.driver_lock:
            whatsapp.open_whatsapp()

        sheets.ensure_reply_type_column(tab)
        classify_existing_replies(tab)

        log.info(f"Fetching up to {count} candidates from row {start_row} in '{tab}'...")
        try:
            candidates = sheets.get_candidates(tab, start_row, count)
        except Exception as e:
            log.error(f"Could not fetch candidates: {e}")
            return

        if not candidates:
            log.error("No eligible candidates found.")
            return

        log.info("=" * 60)
        log.info(f"  CAMPAIGN MODE — tab: '{tab}' | role: {role}")
        log.info(f"  {len(candidates)} candidate(s) from row {start_row}")
        log.info(f"  Gaps: {config.WITHIN_BATCH_GAP_MIN//60}–{config.WITHIN_BATCH_GAP_MAX//60} min within batch | "
                 f"{config.BATCH_GAP_MIN//60}–{config.BATCH_GAP_MAX//60} min between batches")
        log.info("=" * 60)

        # Re-queue any deferred items first, then add new Msg1 batch
        n_deferred = _requeue_deferred()
        if n_deferred:
            log.info(f"[Main] {n_deferred} deferred item(s) from yesterday queued first")
        _queue_msg1_batch(candidates, role, templates)

        monitor_done_event = threading.Event()
        t_sender  = threading.Thread(target=sender_worker,  args=(monitor_done_event,),          name="Sender",  daemon=True)
        t_monitor = threading.Thread(target=monitor_worker, args=(templates, monitor_done_event), name="Monitor", daemon=True)
        t_report  = threading.Thread(target=report_worker,  name="Report", daemon=True)

        t_sender.start()
        t_monitor.start()
        t_report.start()
        log.info("[Main] All workers started (campaign mode).\n")

        try:
            for t in [t_sender, t_monitor, t_report]:
                t.join()
        except KeyboardInterrupt:
            log.info("\n[Main] Stopped by user.")
            log.info(_pipeline_summary())
        log.info("[Main] Automation finished.")
        return

    # ── Resume mode ───────────────────────────────────────────────────────────
    if "--resume" in args:
        _load_state()
        if not pipeline:
            log.error("Nothing to resume — state.json is empty or missing.")
            return

        try:
            templates = load_templates()
        except FileNotFoundError as e:
            log.error(str(e))
            return

        log.info("=" * 60)
        log.info(f"  RESUME MODE — {len(pipeline)} candidate(s) from state.json")
        for phone, info in pipeline.items():
            log.info(f"    {info['name']} ({phone}) — replied={info['replied']} "
                     f"msg1={bool(info['msg1_sent_at'])} msg2={bool(info['msg2_sent_at'])} "
                     f"msg3={bool(info['msg3_sent_at'])}")
        log.info("=" * 60)

        log.info("Opening WhatsApp Web...")
        with whatsapp.driver_lock:
            whatsapp.open_whatsapp()

        active_tabs = list({info["tab"] for info in pipeline.values() if info.get("tab")})
        for t in active_tabs:
            classify_existing_replies(t)

        # Re-queue deferred items
        n_deferred = _requeue_deferred()
        if n_deferred:
            log.info(f"[Main] {n_deferred} deferred item(s) re-queued")

        monitor_done_event = threading.Event()
        if send_queue.empty():
            # Nothing to send right now — sender exits immediately, monitor handles everything
            monitor_done_event.set()

        t_sender  = threading.Thread(target=sender_worker,  args=(monitor_done_event,),          name="Sender",  daemon=True)
        t_monitor = threading.Thread(target=monitor_worker, args=(templates, monitor_done_event), name="Monitor", daemon=True)
        t_report  = threading.Thread(target=report_worker,  name="Report", daemon=True)

        t_sender.start()
        t_monitor.start()
        t_report.start()
        log.info("[Main] Workers started (resume mode). Press Ctrl+C to stop.\n")

        try:
            for t in [t_sender, t_monitor, t_report]:
                t.join()
        except KeyboardInterrupt:
            log.info("\n[Main] Stopped by user.")
            log.info(_pipeline_summary())
        log.info("[Main] Automation finished.")
        return

    # ── Interactive mode ──────────────────────────────────────────────────────
    candidates, role, tab, templates = startup_flow()
    if candidates is None:
        return

    _load_state()

    log.info("Opening WhatsApp Web...")
    with whatsapp.driver_lock:
        whatsapp.open_whatsapp()

    classify_existing_replies(tab)

    n_deferred = _requeue_deferred()
    if n_deferred:
        log.info(f"[Main] {n_deferred} deferred item(s) from yesterday queued first")
    _queue_msg1_batch(candidates, role, templates)

    monitor_done_event = threading.Event()
    t_sender  = threading.Thread(target=sender_worker,  args=(monitor_done_event,),          name="Sender",  daemon=True)
    t_monitor = threading.Thread(target=monitor_worker, args=(templates, monitor_done_event), name="Monitor", daemon=True)
    t_report  = threading.Thread(target=report_worker,  name="Report", daemon=True)

    t_sender.start()
    t_monitor.start()
    t_report.start()
    log.info("[Main] All workers started.\n")

    try:
        for t in [t_sender, t_monitor, t_report]:
            t.join()
    except KeyboardInterrupt:
        log.info("\n[Main] Stopped by user.")
        log.info(_pipeline_summary())
    log.info("[Main] Automation finished.")


if __name__ == "__main__":
    main()
