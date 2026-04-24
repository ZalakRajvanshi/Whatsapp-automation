"""
test.py - Send a single test WhatsApp message via WhatsApp Web

Usage:
    python test.py

- Opens Chrome automatically (no manual chromedriver setup needed)
- Asks which number to send to
- Sends one test message
- No API keys or credentials needed
"""

import time
import sys

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("\n[Error] Run:  pip install selenium webdriver-manager")
    sys.exit(1)

try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("\n[Error] Run:  pip install webdriver-manager")
    sys.exit(1)

# ── Message template ──────────────────────────────────────────────────────────
MESSAGE = "Hey! This is a test message from the WhatsApp Automation bot. Everything is working correctly :)"

# ── Ask for phone number ──────────────────────────────────────────────────────
print("\n" + "=" * 55)
print("  WhatsApp Automation - Test Message Sender")
print("=" * 55)
print("\nThis will open Chrome, load WhatsApp Web, and send")
print("one test message to the number you provide.\n")

phone = input("Enter phone number with country code (e.g. +91XXXXXXXXXX): ").strip()
if not phone:
    print("[Error] Phone number cannot be empty.")
    sys.exit(1)

phone_clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
if not phone_clean.startswith("+"):
    phone_clean = "+91" + phone_clean

print(f"\nSending to : {phone_clean}")
print(f"Message    : {MESSAGE}")
confirm = input("\nType YES to continue: ").strip()
if confirm != "YES":
    print("Cancelled.")
    sys.exit(0)

# ── Launch Chrome ─────────────────────────────────────────────────────────────
print("\n[Setup] Downloading/checking chromedriver...")
opts = Options()
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--start-maximized")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})
print("[Setup] Chrome launched.")
 
# ── Open WhatsApp Web ─────────────────────────────────────────────────────────
print("\n[WhatsApp] Opening WhatsApp Web...")
driver.get("https://web.whatsapp.com")
print("[WhatsApp] Scan the QR code with your phone if prompted.")
print("           WhatsApp -> Linked Devices -> Link a Device\n")

try:
    WebDriverWait(driver, 120).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="chat-list"], #side'))
    )
    print("[WhatsApp] Logged in!\n")
except Exception:
    print("[Error] Timed out. Please try again.")
    driver.quit()
    sys.exit(1)

# ── Open chat with the number ─────────────────────────────────────────────────
print(f"[WhatsApp] Opening chat with {phone_clean}...")
driver.get(f"https://web.whatsapp.com/send?phone={phone_clean}")
time.sleep(5)

# Check for invalid number error
try:
    body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    if "invalid phone" in body_text or "phone number shared via url is invalid" in body_text:
        print(f"[Error] {phone_clean} is not on WhatsApp.")
        driver.quit()
        sys.exit(1)
except Exception:
    pass

# ── Find the message input box ────────────────────────────────────────────────
print("[WhatsApp] Finding message box...")
msg_box = None
for sel in [
    'footer div[contenteditable="true"]',
    '[data-testid="conversation-compose-box-input"]',
    'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"]',
]:
    try:
        msg_box = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
        )
        if msg_box:
            break
    except Exception:
        continue

if not msg_box:
    print("[Error] Could not find the message box. Is the number on WhatsApp?")
    driver.quit()
    sys.exit(1)

# ── Type and send ─────────────────────────────────────────name───────────────────
print("[WhatsApp] Typing message...")
time.sleep(2)
msg_box.click()
time.sleep(1)

for char in MESSAGE:
    if char == "\n":
        ActionChains(driver).key_down(Keys.SHIFT).send_keys(Keys.RETURN).key_up(Keys.SHIFT).perform()
    else:
        msg_box.send_keys(char)
    time.sleep(0.04)

time.sleep(1)
msg_box.send_keys(Keys.ENTER)
time.sleep(2)

print(f"\n[WhatsApp] Message sent to {phone_clean}!")
print("\n" + "=" * 55)
print("  Test complete - automation is working!")
print("=" * 55 + "\n")

input("Press Enter to close the browser...")
driver.quit()
