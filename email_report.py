"""
Daily recruitment outreach email report — HTML format.
Sent automatically at 7 PM by the report_worker thread in main.py.
Can also be triggered manually: python3 send_report.py
"""

import random
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
import sheets


def build_report(tab_name: str) -> dict:
    today_str = datetime.now().strftime("%Y-%m-%d")
    stats     = sheets.get_daily_stats(tab_name, today_str)
    return {
        "date":  datetime.now().strftime("%d %B %Y"),
        "tab":   tab_name,
        "stats": stats,
    }


def _has_classified_replies(stats: dict) -> bool:
    """Return True only if this tab has at least one reply classified as Positive/Negative/Neutral."""
    valid = {config.REPLY_TYPE_POSITIVE, config.REPLY_TYPE_NEGATIVE, config.REPLY_TYPE_NEUTRAL}
    return any(c["reply_type"] in valid for c in stats.get("replied_candidates", []))


def _name_bullets(replied_candidates: list, rtype: str) -> str:
    matches = [c for c in replied_candidates if c["reply_type"] == rtype]
    if not matches:
        return "<li style='list-style:none; color:#aaa; font-size:12px; padding:2px 0;'>None so far</li>"
    return "".join(
        f"<li style='margin-bottom:5px; font-size:13px; color:#1f2937;'>"
        f"<strong>{c['name']}</strong>"
        f"<span style='color:#888; font-size:12px;'> &nbsp;{c['role']}</span>"
        f"</li>"
        for c in matches
    )


def _format_tab_section(report: dict) -> str:
    """Return the HTML block for one campaign tab (no <html>/<body> wrapper)."""
    s    = report["stats"]
    tab  = report["tab"]
    rc   = s.get("reply_type_counts", {})

    msg1               = s.get("msg1_sent_today", 0)
    msg2               = s.get("msg2_sent_today", 0)
    msg3               = s.get("msg3_sent_today", 0)
    total              = s.get("total_outreach_today", 0)
    replied            = s.get("replied_total", 0)
    positive           = rc.get(config.REPLY_TYPE_POSITIVE, 0)
    negative           = rc.get(config.REPLY_TYPE_NEGATIVE, 0)
    neutral            = rc.get(config.REPLY_TYPE_NEUTRAL,  0)
    wait1              = s.get("waiting_on_msg1", 0)
    wait2              = s.get("waiting_on_msg2", 0)
    waiting            = s.get("waiting_total", 0)
    replied_candidates = s.get("replied_candidates", [])

    def pl(n, word):
        return f"{n} {word}" if n == 1 else f"{n} {word}s"

    total_reached_out = replied + waiting + s.get("completed", 0)
    rate       = round((replied / total_reached_out) * 100) if total_reached_out else 0
    rate_color = "#2e7d32" if rate >= 30 else "#e65100" if rate < 15 else "#1565c0"
    rate_label = "Great conversion!" if rate >= 30 else "Keep going!" if rate < 15 else "Solid progress!"

    # Outreach summary
    if total == 0:
        outreach_html = "No new messages went out today — automation was in monitoring mode."
    else:
        parts = []
        if msg1: parts.append(f"<strong>{msg1}</strong> received their First Message")
        if msg2: parts.append(f"<strong>{msg2}</strong> received Follow-up Message 1")
        if msg3: parts.append(f"<strong>{msg3}</strong> received Follow-up Message 2")
        outreach_html = (
            f"Sent <strong>{total} message(s)</strong> today "
            f"({', '.join(parts)})."
        )

    # Pipeline status
    if waiting == 0:
        pipeline_html = "Everyone has either replied or finished the full sequence."
    else:
        parts = []
        if wait1: parts.append(f"<strong>{wait1}</strong> waiting after First Message")
        if wait2: parts.append(f"<strong>{wait2}</strong> waiting after Follow-up Message 1")
        pipeline_html = (
            f"<strong>{waiting}</strong> candidate(s) still active in pipeline "
            f"({', '.join(parts)}). Follow-ups will be sent automatically."
        )

    # Next steps
    steps = []
    if wait1:
        steps.append(
            f"{pl(wait1, 'candidate')} waiting after the First Message will automatically "
            f"receive Follow-up Message 1 at the 36-hour mark."
        )
    if wait2:
        steps.append(
            f"{pl(wait2, 'candidate')} waiting after Follow-up Message 1 will automatically "
            f"receive Follow-up Message 2 at the 36-hour mark."
        )
    if positive:
        steps.append(
            f"{pl(positive, 'candidate')} responded positively — consider scheduling a call "
            f"or sharing the JD directly."
        )
    if neutral:
        steps.append(
            f"{pl(neutral, 'candidate')} gave a neutral response — "
            f"a personalised follow-up could help move them forward."
        )
    if not steps:
        steps.append("All sequences are on track — nothing urgent to action right now.")

    steps_html = "".join(f"<li style='margin-bottom:8px;'>{st}</li>" for st in steps)

    pos_bullets = _name_bullets(replied_candidates, config.REPLY_TYPE_POSITIVE)
    neg_bullets = _name_bullets(replied_candidates, config.REPLY_TYPE_NEGATIVE)
    neu_bullets = _name_bullets(replied_candidates, config.REPLY_TYPE_NEUTRAL)

    return f"""
    <!-- ── Campaign: {tab} ── -->
    <div style="margin-bottom:36px;">

      <!-- Tab heading -->
      <div style="background:#f3f4f6; border-radius:6px; padding:10px 16px; margin-bottom:20px;">
        <p style="margin:0; font-size:13px; font-weight:700; color:#374151;
                  letter-spacing:0.5px; text-transform:uppercase;">{tab}</p>
      </div>

      <!-- Outreach Today -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
        <tr>
          <td style="border-left:4px solid #111827; padding-left:14px;">
            <p style="margin:0 0 3px 0; font-size:11px; font-weight:700;
                      color:#9ca3af; letter-spacing:1.2px; text-transform:uppercase;">Outreach Today</p>
            <p style="margin:0; font-size:14px; color:#1f2937; line-height:1.6;">{outreach_html}</p>
          </td>
        </tr>
      </table>

      <!-- Reply stats -->
      <p style="margin:0 0 10px 0; font-size:11px; font-weight:700;
                color:#9ca3af; letter-spacing:1.2px; text-transform:uppercase;">Replies &amp; Sentiment</p>

      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
        <tr>
          <td width="30%" style="background:#111827; border-radius:8px; padding:14px 16px; text-align:center;">
            <p style="margin:0; font-size:30px; font-weight:700; color:#ffffff;">{total_reached_out}</p>
            <p style="margin:4px 0 0 0; font-size:12px; color:#9ca3af;">Reached Out</p>
          </td>
          <td width="4%"></td>
          <td width="30%" style="background:#111827; border-radius:8px; padding:14px 16px; text-align:center;">
            <p style="margin:0; font-size:30px; font-weight:700; color:#ffffff;">{replied}</p>
            <p style="margin:4px 0 0 0; font-size:12px; color:#9ca3af;">Replied</p>
          </td>
          <td width="4%"></td>
          <td width="32%" style="background:#f9fafb; border:1px solid #e5e7eb;
                border-radius:8px; padding:14px 16px; text-align:center;">
            <p style="margin:0; font-size:26px; font-weight:700; color:{rate_color};">{rate}%</p>
            <p style="margin:4px 0 0 0; font-size:12px; color:#6b7280;">Response Rate</p>
            <p style="margin:2px 0 0 0; font-size:11px; color:{rate_color};">{rate_label}</p>
          </td>
        </tr>
      </table>

      <!-- Sentiment cards with bullet names -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
        <tr>
          <td width="32%" valign="top"
              style="background:#f0fdf4; border:1px solid #bbf7d0;
                     border-radius:8px; padding:12px 14px;">
            <p style="margin:0 0 8px 0; font-size:12px; font-weight:700; color:#15803d;">
              Positive &nbsp;({positive})</p>
            <ul style="margin:0; padding-left:16px; list-style:disc;">
              {pos_bullets}
            </ul>
          </td>
          <td width="4%"></td>
          <td width="32%" valign="top"
              style="background:#fff1f2; border:1px solid #fecdd3;
                     border-radius:8px; padding:12px 14px;">
            <p style="margin:0 0 8px 0; font-size:12px; font-weight:700; color:#be123c;">
              Negative &nbsp;({negative})</p>
            <ul style="margin:0; padding-left:16px; list-style:disc;">
              {neg_bullets}
            </ul>
          </td>
          <td width="4%"></td>
          <td width="32%" valign="top"
              style="background:#fffbeb; border:1px solid #fde68a;
                     border-radius:8px; padding:12px 14px;">
            <p style="margin:0 0 8px 0; font-size:12px; font-weight:700; color:#b45309;">
              Neutral &nbsp;({neutral})</p>
            <ul style="margin:0; padding-left:16px; list-style:disc;">
              {neu_bullets}
            </ul>
          </td>
        </tr>
      </table>

      <!-- Pipeline -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
        <tr>
          <td style="border-left:4px solid #6366f1; padding-left:14px;">
            <p style="margin:0 0 3px 0; font-size:11px; font-weight:700;
                      color:#9ca3af; letter-spacing:1.2px; text-transform:uppercase;">Pipeline Status</p>
            <p style="margin:0; font-size:14px; color:#1f2937; line-height:1.6;">{pipeline_html}</p>
          </td>
        </tr>
      </table>

      <!-- Next Steps -->
      <p style="margin:0 0 8px 0; font-size:11px; font-weight:700;
                color:#9ca3af; letter-spacing:1.2px; text-transform:uppercase;">Next Steps</p>
      <ul style="margin:0; padding-left:20px; font-size:13px; color:#374151; line-height:1.7;">
        {steps_html}
      </ul>

    </div>
"""


def _deferred_section_html(deferred_items: list) -> str:
    """HTML block shown at the bottom of the email when items were deferred to tomorrow."""
    if not deferred_items:
        return ""

    counts = {}
    for item in deferred_items:
        t = item.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1

    breakdown = ", ".join(
        f"{v} {k.upper()}" for k, v in sorted(counts.items())
    )

    names_html = "".join(
        f"<li style='margin-bottom:4px; font-size:13px; color:#1f2937;'>"
        f"<strong>{item.get('name', '?')}</strong>"
        f"<span style='color:#888; font-size:12px;'> &nbsp;{item.get('type','').upper()}</span>"
        f"</li>"
        for item in deferred_items[:15]
    )
    if len(deferred_items) > 15:
        names_html += (
            f"<li style='font-size:12px; color:#9ca3af; list-style:none;'>"
            f"… and {len(deferred_items) - 15} more</li>"
        )

    return f"""
    <!-- Deferred section -->
    <div style="margin-top:32px; background:#fffbeb; border:1px solid #fde68a;
                border-radius:8px; padding:18px 20px;">
      <p style="margin:0 0 6px 0; font-size:12px; font-weight:700; color:#b45309;
                letter-spacing:1px; text-transform:uppercase;">
        Deferred to Tomorrow ({len(deferred_items)} messages)
      </p>
      <p style="margin:0 0 12px 0; font-size:13px; color:#374151;">
        The daily limit of {__import__('config').MAX_DAILY_MESSAGES} messages was reached today.
        {breakdown} will be sent automatically tomorrow when the automation resumes.
      </p>
      <ul style="margin:0; padding-left:18px;">
        {names_html}
      </ul>
    </div>
"""


def _build_combined_html(reports: list, deferred_items: list = None) -> str:
    date = reports[0]["date"] if reports else datetime.now().strftime("%d %B %Y")
    tab_count = len(reports)
    campaign_label = f"{tab_count} Campaign{'s' if tab_count > 1 else ''}"

    opening = random.choice([
        f"Here's your end-of-day recruitment update for <strong>{date}</strong>. Let's get into it.",
        f"Quick wrap-up for <strong>{date}</strong> — here's how the outreach is looking.",
        f"End of day, <strong>{date}</strong>. Here's where things stand on the recruitment front.",
        f"Here's your daily recruitment pulse for <strong>{date}</strong>.",
        f"Checking in with today's numbers for <strong>{date}</strong>. Here's the full picture.",
    ])

    closing = random.choice([
        "We'll keep the momentum going tomorrow — stay tuned!",
        "Onwards and upwards — more outreach coming tomorrow!",
        "We're on it. More updates tomorrow!",
        "The pipeline is moving. More tomorrow!",
        "That's a wrap for today. Let's see what tomorrow brings!",
    ])

    # Divider between campaigns
    divider = "<hr style='border:none; border-top:1px solid #e5e7eb; margin:0 0 32px 0;'>"
    sections_html = divider.join(_format_tab_section(r) for r in reports)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f0f2f5;
             font-family:'Helvetica Neue',Arial,sans-serif;">

  <div style="max-width:660px; margin:36px auto;">

    <!-- Header -->
    <div style="background:#111827; border-radius:10px 10px 0 0; padding:30px 36px;">
      <p style="margin:0 0 4px 0; font-size:12px; color:#9ca3af;
                letter-spacing:1.5px; text-transform:uppercase;">Recruitment Automation</p>
      <h1 style="margin:0; font-size:24px; font-weight:700; color:#ffffff;">
        Recruitment Report
      </h1>
      <p style="margin:8px 0 0 0; font-size:14px; color:#d1d5db;">
        {date} &nbsp;&bull;&nbsp; {campaign_label}
      </p>
    </div>

    <!-- Body -->
    <div style="background:#ffffff; padding:32px 36px;">

      <p style="margin:0 0 28px 0; font-size:15px; color:#374151; line-height:1.7;">
        Hi team,<br><br>{opening}
      </p>

      {sections_html}

      {_deferred_section_html(deferred_items or [])}

      <p style="margin:28px 0 0 0; font-size:15px; color:#374151;">{closing}</p>

    </div>

    <!-- Footer -->
    <div style="background:#f9fafb; border-top:1px solid #e5e7eb;
                border-radius:0 0 10px 10px; padding:16px 36px;
                text-align:center; font-size:12px; color:#9ca3af;">
      Recruitment Automation Bot &nbsp;&bull;&nbsp; Automated Daily Report
    </div>

  </div>

</body>
</html>"""


def send_combined_report(tabs: list, deferred_items: list = None) -> bool:
    """
    Build one email covering all tabs that have actual outreach, and send it.
    Skips tabs with zero candidates ever contacted.
    Pass deferred_items to include a "deferred to tomorrow" section in the email.
    """
    if not config.GMAIL_SENDER or not config.GMAIL_APP_PASSWORD:
        print("[Report] Gmail credentials not configured — skipping EOD report.")
        return False
    if not config.REPORT_RECIPIENTS:
        print("[Report] REPORT_RECIPIENTS is empty — skipping EOD report.")
        return False

    try:
        reports = []
        for tab in tabs:
            r = build_report(tab)
            if _has_classified_replies(r["stats"]):
                reports.append(r)
            else:
                print(f"[Report] '{tab}' has no classified replies yet — skipping.")

        if not reports:
            print("[Report] No active campaigns with outreach — skipping report.")
            return False

        date    = reports[0]["date"]
        html    = _build_combined_html(reports, deferred_items=deferred_items or [])
        subject = f"Recruitment Report — {date}"

        msg            = MIMEMultipart("alternative")
        msg["From"]    = config.GMAIL_SENDER
        msg["To"]      = ", ".join(config.REPORT_RECIPIENTS)
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.GMAIL_SENDER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_SENDER, config.REPORT_RECIPIENTS, msg.as_string())

        tab_names = ", ".join(r["tab"] for r in reports)
        print(f"[Report] Sent 1 combined email ({len(reports)} campaign(s): {tab_names}) "
              f"to {', '.join(config.REPORT_RECIPIENTS)}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("[Report] Gmail auth failed — check GMAIL_SENDER and GMAIL_APP_PASSWORD.")
        return False
    except Exception as e:
        print(f"[Report] Error: {e}")
        return False


def send_daily_report(tab_name: str) -> bool:
    """Backward-compat wrapper — sends a combined report for a single tab."""
    return send_combined_report([tab_name])
