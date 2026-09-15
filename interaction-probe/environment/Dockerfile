
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install python3-pip and ALL Chromium system dependencies for Playwright headless browser
# libasound2t64 is required on Ubuntu 24.04 (time_t transition renamed libasound2)
RUN apt-get update && apt-get install -y \
    python3-pip \
    libasound2t64 \
    libnss3 libnspr4 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
    libcairo2 libcups2 libdbus-1-3 libdrm2 libgbm1 \
    libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 \
    libxdamage1 libxext6 libxfixes3 libxkbcommon0 \
    libxrandr2 libxshmfence1 fonts-liberation libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Pre-install Playwright and download Chromium browser binary during build.
RUN pip3 install playwright==1.49.0 \
    && python3 -m playwright install chromium

COPY webapp/ /app/webapp/

WORKDIR /app
