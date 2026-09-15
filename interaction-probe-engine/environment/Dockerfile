
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install playwright==1.49.1

RUN playwright install --with-deps && rm -rf /var/lib/apt/lists/*

COPY pages/ /app/pages/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 playwright==1.49.1
