#!/usr/bin/env bash

export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# Ensure Playwright browsers are available (fallback if Docker layer missed them)
python3 -m playwright install chromium-headless-shell 2>/dev/null || true

# Deploy the interaction probe to the expected location
cp /solution/probe.py /app/interaction_probe.py
chmod +x /app/interaction_probe.py

# Verify the probe can launch the browser
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'])
    browser.close()
print('Browser launch verification passed')
"

echo "Interaction probe installed at /app/interaction_probe.py"
