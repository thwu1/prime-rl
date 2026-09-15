
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

RUN apt-get update && apt-get install -y \
    python3-pip \
    sudo \
    ca-certificates \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install playwright==1.49.1 && \
    apt-get update && \
    python3 -m playwright install --with-deps chromium chromium-headless-shell && \
    rm -rf /var/lib/apt/lists/*

COPY samples/ /app/samples/
COPY schema.json /app/schema.json

WORKDIR /app
