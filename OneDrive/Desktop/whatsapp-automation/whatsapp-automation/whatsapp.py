"""
WhatsApp Web automation using Selenium + Chrome.
- Persistent Chrome profile (QR scan once).
- Human-like typing: character by character, NO URL text prefill.
- driver_lock: acquire before every call from main.py threads.
"""

import subprocess
import time
import random
import threading

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
CHROMEDRIVER_PATH = "/opt/homebrew/bin/chromedriver"

import config

_driver = None
REMOTE_DEBUG_PORT = 9222

# Acquire this lock in main.py before ANY whatsapp function that uses the browser
driver_lock = threading.Lock()


# ── Driver management ──────────────────────────────────────────────────────

def get_driver():
    global _driver
    if _driver is not None:
        try:
            _ = _driver.title
            return _driver
        except Exception:
            _driver = None

    # Try reconnecting to existing Chrome
    try:
        opts = Options()
        opts.debugger_address = f"127.0.0.1:{REMOTE_DEBUG_PORT}"
        svc = Service(CHROMEDRIVER_PATH)
        _driver = webdriver.Chrome(service=svc, options=opts)
        print(f"[WhatsApp] Reconnected to existing Chrome on port {REMOTE_DEBUG_PORT}")
        return _driver
    except Exception:
        pass

    # Start fresh Chrome
    opts = Options()
    opts.add_argument(f"--user-data-dir={config.CHROME_PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument(f"--remote-debugging-port={REMOTE_DEBUG_PORT}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--remote-allow-origins=*")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("detach", True)

    svc = Service(CHROMEDRIVER_PATH)
    _driver = webdriver.Chrome(service=svc, options=opts)
    _driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    print(f"[WhatsApp] Started new Chrome on port {REMOTE_DEBUG_PORT}")
    return _driver


def open_whatsapp():
    """Open WhatsApp Web and wait for it to be ready."""
    driver = get_driver()
    driver.get("https://web.whatsapp.com")
    print("[WhatsApp] Waiting for WhatsApp Web to load...")
    print("[WhatsApp] If first time: scan the QR code in the browser window.")
    try:
        WebDriverWait(driver, 90).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="chat-list"]'))
        )
        print("[WhatsApp] WhatsApp Web loaded.")
    except Exception:
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#side"))
            )
            print("[WhatsApp] WhatsApp Web loaded.")
        except Exception as e:
            print(f"[WhatsApp] Warning: Could not confirm load: {e}")


# ── Human-behaviour helpers ────────────────────────────────────────────────

def _random_mouse_jitter(driver):
    try:
        actions = ActionChains(driver)
        vw = driver.execute_script("return window.innerWidth")
        vh = driver.execute_script("return window.innerHeight")
        for _ in range(random.randint(2, 4)):
            x = random.randint(100, max(200, vw - 200))
            y = random.randint(100, max(200, vh - 200))
            actions.move_by_offset(x // 10, y // 10)
            actions.pause(random.uniform(0.1, 0.3))
        actions.perform()
    except Exception:
        pass


def _random_scroll(driver):
    try:
        scroll_up = random.randint(100, 400)
        driver.execute_script(f"window.scrollBy(0, -{scroll_up});")
        time.sleep(random.uniform(0.5, 1.2))
        driver.execute_script("window.scrollBy(0, 9999);")
        time.sleep(random.uniform(0.3, 0.7))
    except Exception:
        pass


def _has_non_bmp(text):
    """Return True if text contains characters outside Unicode BMP (e.g. emoji)."""
    return any(ord(c) > 0xFFFF for c in text)


def _type_humanlike(element, text, driver):
    """
    Type text character by character at 40-80 WPM.
    Falls back to clipboard paste (pbcopy + Cmd+V) for messages with emoji
    since ChromeDriver send_keys() only supports BMP characters.
    """
    try:
        driver.execute_script("arguments[0].click();", element)
        time.sleep(random.uniform(0.3, 0.7))
    except Exception:
        pass

    if _has_non_bmp(text):
        # Clipboard paste path — handles emoji
        # Clear any existing content first to prevent duplicates
        try:
            element.send_keys(Keys.COMMAND + 'a')
            time.sleep(0.1)
            element.send_keys(Keys.BACKSPACE)
            time.sleep(0.1)
        except Exception:
            pass
        try:
            proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'))
            time.sleep(random.uniform(0.3, 0.6))
            # Use ActionChains for reliable Cmd+V on macOS
            ActionChains(driver).key_down(Keys.COMMAND).send_keys('v').key_up(Keys.COMMAND).perform()
            time.sleep(random.uniform(0.8, 2.0))
            return
        except Exception:
            pass  # fall through to char-by-char if pbcopy fails

    wpm = random.uniform(40, 80)
    base_delay = 60.0 / (wpm * 5)  # seconds per character

    for i, char in enumerate(text):
        delay = base_delay * random.uniform(0.5, 1.8)
        if char in ('.', ',', '!', '?') or (random.random() < 0.03 and i > 10):
            delay += random.uniform(0.3, 0.8)

        if char == '\n':
            # Shift+Enter = new line inside WhatsApp (plain Enter = sends the message)
            ActionChains(driver).key_down(Keys.SHIFT).send_keys(Keys.RETURN).key_up(Keys.SHIFT).perform()
        else:
            element.send_keys(char)
        time.sleep(delay)

        # ~3% chance of typo → backspace and retype
        if random.random() < 0.03 and i < len(text) - 1:
            element.send_keys(random.choice("abcdefghijklmnopqrstuvwxyz"))
            time.sleep(random.uniform(0.2, 0.5))
            element.send_keys(Keys.BACKSPACE)
            time.sleep(random.uniform(0.1, 0.3))

    time.sleep(random.uniform(0.8, 2.0))  # pause after typing — like reviewing


def _distraction_pause():
    """
    Random natural pauses to simulate human distraction:
      - 30% chance: short pause (8–20s) — glanced at something
      - 10% chance: long pause (30–90s) — got distracted / switched tabs
    """
    r = random.random()
    if r < 0.10:
        pause = random.uniform(30, 90)
        print(f"[Human] Long distraction pause: {pause:.0f}s")
        time.sleep(pause)
    elif r < 0.30:
        pause = random.uniform(8, 20)
        print(f"[Human] Short distraction pause: {pause:.0f}s")
        time.sleep(pause)


def _find_compose_box(driver, timeout=25):
    """Try multiple selectors to find the compose box. Returns element or None."""
    selectors = [
        'footer div[contenteditable="true"]',
        '[data-testid="conversation-compose-box-input"]',
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"][data-tab="10"]',
        'div[contenteditable="true"]',
    ]
    for sel in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
            )
            if el:
                return el
        except Exception:
            timeout = 5  # shorter for subsequent attempts
    return None


# ── Message sending ────────────────────────────────────────────────────────

class NotOnWhatsAppError(Exception):
    """Raised when a phone number is not registered on WhatsApp."""
    pass


def _check_invalid_number(driver) -> bool:
    """
    Returns True if WhatsApp shows an 'invalid phone number' error popup.
    Checked immediately after page load to skip non-WA numbers fast.
    """
    try:
        error_texts = [
            "Phone number shared via url is invalid",
            "phone number shared via url is invalid",
            "invalid phone",
        ]
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        for t in error_texts:
            if t.lower() in page_text:
                return True
        # Also check for alert popup
        alerts = driver.find_elements(By.CSS_SELECTOR,
            '[data-testid="alert-popup"], [role="alertdialog"]')
        for alert in alerts:
            if "invalid" in alert.text.lower() or "phone number" in alert.text.lower():
                return True
    except Exception:
        pass
    return False


def _verify_correct_chat(driver, phone_clean: str, timeout: int = 6) -> bool:
    """
    Check the URL right after navigation — while it still contains the phone number
    in the /send?phone= parameter (before WhatsApp redirects to the chat view).
    Contacts saved by name won't appear as numbers in the header, so URL is the
    only reliable signal immediately post-navigation.
    """
    digits = ''.join(filter(str.isdigit, phone_clean))[-10:]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            url_digits = ''.join(filter(str.isdigit, driver.current_url))
            if digits in url_digits:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _get_active_chat_url(driver) -> str:
    """Return current URL — used to detect if chat switched during typing."""
    try:
        return driver.current_url
    except Exception:
        return ""


def _try_send_once(driver, phone_clean: str, message: str) -> bool:
    """Single attempt. Returns True on success. Raises NotOnWhatsAppError if number is invalid."""
    # Navigate to chat — NO text prefill in URL
    url = f"https://web.whatsapp.com/send?phone={phone_clean}"
    driver.get(url)
    print(f"[WhatsApp] Opening chat with {phone_clean}...")

    # Verify URL contains the right phone number right after navigation
    # (before WhatsApp redirects away from /send?phone=)
    if not _verify_correct_chat(driver, phone_clean):
        print(f"[WhatsApp] Navigation failed for {phone_clean} — aborting")
        return False

    # Handle "Continue to chat" popup
    try:
        btn = WebDriverWait(driver, 6).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="popup-continue"]'))
        )
        btn.click()
        time.sleep(2)
    except Exception:
        pass

    # Handle "Use Here" multi-device prompt
    try:
        btn = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.XPATH,
                "//*[contains(text(),'Use Here') or contains(text(),'Use on This Computer')]"))
        )
        btn.click()
        time.sleep(3)
    except Exception:
        pass

    # Let page settle
    time.sleep(random.uniform(4.0, 6.0))

    # Early check: bail out immediately if number is not on WhatsApp
    if _check_invalid_number(driver):
        raise NotOnWhatsAppError(f"{phone_clean} is not on WhatsApp")

    _random_mouse_jitter(driver)
    time.sleep(random.uniform(0.5, 1.5))
    _random_scroll(driver)

    # Find compose box
    msg_box = _find_compose_box(driver, timeout=20)
    if not msg_box:
        return False

    # Snapshot chat URL before typing — to detect if someone clicks away
    chat_url_before = _get_active_chat_url(driver)

    # Pause before typing (like reading the chat first)
    time.sleep(random.uniform(2.0, 5.0))

    # ── Typing indicator phase ─────────────────────────────────────────────
    # Click the compose box — this triggers the "typing..." indicator on the
    # recipient's side (the 3 dots). We then wait a realistic reading/thinking
    # time before actually starting to type, so the indicator appears naturally.
    try:
        driver.execute_script("arguments[0].focus();", msg_box)
        time.sleep(random.uniform(0.3, 0.7))
        # "Reading" pause — proportional to message length (looks like we're
        # re-reading a draft before sending). Roughly 1s per 20 chars, capped.
        reading_pause = min(random.uniform(3.0, 6.0) + len(message) / 80, 12.0)
        print(f"[Human] Typing indicator active — reading pause {reading_pause:.1f}s")
        time.sleep(reading_pause)
    except Exception:
        pass

    # Type message character by character
    _type_humanlike(msg_box, message, driver)

    # Safety check: abort if chat switched during typing
    chat_url_after = _get_active_chat_url(driver)
    if chat_url_after != chat_url_before:
        print(f"[WhatsApp] ⚠️  Chat switched during typing — aborting send for {phone_clean}")
        return False

    # Send via Enter (primary)
    sent = False
    try:
        msg_box.send_keys(Keys.ENTER)
        sent = True
    except Exception:
        pass

    # Fallback: click send button
    if not sent:
        for sel in ['[data-testid="compose-btn-send"]', 'span[data-icon="send"]', '[aria-label="Send"]']:
            try:
                driver.find_element(By.CSS_SELECTOR, sel)
                driver.execute_script("arguments[0].click();",
                                      driver.find_element(By.CSS_SELECTOR, sel))
                sent = True
                break
            except Exception:
                continue

    if sent:
        time.sleep(random.uniform(1.5, 2.5))
    return sent


def verify_last_sent(driver, message: str, timeout: int = 8) -> bool:
    """
    Confirm the last outbound message in the chat contains our message.
    Checks the last 25 characters of the message against .message-out DOM elements.
    Returns True if verified.
    """
    # Use last 25 BMP-only chars for comparison (non-BMP emoji can fail DOM text match)
    bmp_text = ''.join(c for c in message.replace('\n', ' ').strip() if ord(c) <= 0xFFFF)
    check_str = bmp_text[-25:] if bmp_text else message.strip()[-25:]
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in [
            '.message-out .selectable-text span[dir="ltr"]',
            '.message-out span[dir="ltr"]',
            '.message-out .copyable-text',
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els and els[-1].text.strip():
                if check_str in els[-1].text:
                    return True
        time.sleep(0.5)
    return False


def send_message(phone: str, message: str, retries: int = 2) -> bool:
    """
    Send a WhatsApp message with human-like behaviour and retry on failure.
    Verifies the message appeared in chat after sending.
    Returns True on success.
    """
    driver = get_driver()

    phone_clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone_clean.startswith("+"):
        phone_clean = "+91" + phone_clean

    # Random pre-chat pause — varies so sends don't happen at fixed intervals
    pre_pause = random.uniform(3, 12)
    print(f"[Human] Pre-chat pause: {pre_pause:.1f}s")
    time.sleep(pre_pause)
    _distraction_pause()

    for attempt in range(1, retries + 1):
        try:
            sent = _try_send_once(driver, phone_clean, message)
            if sent:
                # Verify message appeared — but don't retry if sent, to avoid duplicates
                verified = verify_last_sent(driver, message)
                if verified:
                    print(f"[WhatsApp] ✓ Message sent and verified for {phone_clean}")
                else:
                    print(f"[WhatsApp] ✓ Message sent for {phone_clean} (verification inconclusive)")
                return True
            else:
                print(f"[WhatsApp] Attempt {attempt}/{retries} — compose box not found for {phone_clean}")
        except NotOnWhatsAppError as e:
            print(f"[WhatsApp] ✗ Skipping {phone_clean} — not on WhatsApp")
            return False  # no retries — number is simply not registered
        except Exception as e:
            print(f"[WhatsApp] Attempt {attempt}/{retries} — error: {e}")

        if attempt < retries:
            wait = random.uniform(8, 15)
            print(f"[WhatsApp] Retrying in {wait:.0f}s...")
            time.sleep(wait)

    print(f"[WhatsApp] All {retries} attempts failed for {phone_clean}")
    return False


# ── Reply detection ────────────────────────────────────────────────────────

def get_all_incoming_messages(phone: str) -> list:
    """
    Open chat and return ALL visible incoming (.message-in) message texts.
    Used to build a baseline snapshot before sending Msg1.
    NOTE: Opening the chat will mark messages as read in WhatsApp.
    """
    driver = get_driver()
    phone_clean = phone.replace(" ", "").replace("-", "")
    if not phone_clean.startswith("+"):
        phone_clean = "+91" + phone_clean

    try:
        driver.get(f"https://web.whatsapp.com/send?phone={phone_clean}")
        time.sleep(3)

        loaded = False
        for sel in [
            'footer div[contenteditable="true"]',
            '[data-testid="conversation-compose-box-input"]',
            'div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"]',
        ]:
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                loaded = True
                break
            except Exception:
                continue

        if not loaded:
            return []

        time.sleep(2)

        texts = []
        for sel in [
            '.message-in .selectable-text span[dir="ltr"]',
            '.message-in span[dir="ltr"]',
            '.message-in .copyable-text span',
            'div.message-in span.selectable-text',
            '.message-in .copyable-text',
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            texts = [e.text.strip() for e in els if e.text.strip()]
            if texts:
                break

        return texts

    except Exception as e:
        print(f"[WhatsApp] Could not fetch messages for {phone_clean}: {e}")
        return []


def has_unread_from(phone: str) -> bool:
    """
    Check WhatsApp sidebar for unread badge — does NOT open the chat.
    Returns True if unread indicator found for this contact.
    """
    driver = get_driver()
    digits = ''.join(filter(str.isdigit, phone))[-10:]

    try:
        if "web.whatsapp.com" not in driver.current_url or "/send?" in driver.current_url:
            driver.get("https://web.whatsapp.com")
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="chat-list"]'))
            )
            time.sleep(2)

        chat_items = driver.find_elements(
            By.CSS_SELECTOR,
            '[data-testid="chat-list"] [data-testid="cell-frame-container"]'
        )
        for item in chat_items:
            try:
                label = item.get_attribute("aria-label") or ""
                title = item.find_element(By.CSS_SELECTOR, '[data-testid="cell-frame-title"]').text
                if digits in label.replace(" ", "").replace("-", "") or \
                   digits in title.replace(" ", "").replace("-", ""):
                    badges = item.find_elements(
                        By.CSS_SELECTOR,
                        '[data-testid="icon-unread-count"], span[aria-label*="unread"]'
                    )
                    if badges:
                        return True
            except Exception:
                continue
        return False
    except Exception:
        return False


# Tracks last time each phone's chat was fully opened for reply check
_last_full_check: dict = {}


def get_new_replies(phone: str, baseline: list) -> list:
    """
    Returns messages received AFTER the baseline snapshot.

    Strategy:
    - Every cycle: check sidebar for unread badge only (fast, no chat open).
      If badge found → open chat immediately to read the reply.
    - Every MONITOR_FULL_CHECK_INTERVAL (2h): open chat regardless of badge.
      Catches replies already read on phone (badge cleared by candidate).
    """
    now  = time.time()
    last = _last_full_check.get(phone, 0)
    due_full_check = (now - last) >= config.MONITOR_FULL_CHECK_INTERVAL

    unread = has_unread_from(phone)

    if not unread and not due_full_check:
        return []

    # Add a random human-like pause before opening the chat
    pause = random.uniform(*config.MONITOR_CHAT_OPEN_DELAY)
    time.sleep(pause)

    print(f"[WhatsApp] Opening chat for reply check: {phone} (unread={unread}, full_check={due_full_check})")
    current = get_all_incoming_messages(phone)
    _last_full_check[phone] = now
    print(f"[WhatsApp] {phone}: baseline={len(baseline)} current={len(current)} msgs")

    if len(current) > len(baseline):
        return current[len(baseline):]
    return []


def close():
    global _driver
    if _driver:
        _driver.quit()
        _driver = None
