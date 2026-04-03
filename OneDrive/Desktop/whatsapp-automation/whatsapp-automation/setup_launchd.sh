#!/bin/bash
# One-time setup: installs bot.py as a background service on Mac.
# After running this, bot.py starts automatically on every boot.
# Run: bash setup_launchd.sh

set -e

PYTHON=$(which python3)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST=~/Library/LaunchAgents/com.tpf.whatsappbot.plist
LOG_DIR="$SCRIPT_DIR/logs"

echo "Python:     $PYTHON"
echo "Script dir: $SCRIPT_DIR"
echo "Plist:      $PLIST"
echo ""

# Install python-telegram-bot if not already installed
echo "Checking dependencies..."
$PYTHON -c "import telegram" 2>/dev/null || {
    echo "Installing python-telegram-bot..."
    $PYTHON -m pip install "python-telegram-bot>=20.0"
}
echo "Dependencies OK."
echo ""

# Create logs dir
mkdir -p "$LOG_DIR"

# Write plist
cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tpf.whatsappbot</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/bot.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>

    <!-- Start on boot and keep alive if it crashes -->
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/bot_error.log</string>
</dict>
</plist>
EOF

echo "Plist written."

# Unload first in case it was already loaded
launchctl unload "$PLIST" 2>/dev/null || true

# Load the service
launchctl load "$PLIST"

echo ""
echo "Done! Bot service is now running and will auto-start on every boot."
echo ""
echo "Useful commands:"
echo "  Check status:  launchctl list | grep tpf"
echo "  View bot logs: tail -f $LOG_DIR/bot.log"
echo "  Stop service:  launchctl unload $PLIST"
echo "  Start service: launchctl load $PLIST"
echo ""
echo "Next: add your TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_IDS to config.py"
