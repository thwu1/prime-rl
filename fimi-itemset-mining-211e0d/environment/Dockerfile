FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    gawk \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY lib/ /app/lib/
COPY fim /app/fim
COPY Makefile /app/Makefile
COPY schema/ /app/schema/
COPY config/ /app/config/
COPY data/ /app/data/
COPY synth_test.dat /app/data/synth_test.dat
COPY mixed_basket.csv /app/data/raw/mixed_basket.csv
COPY docs/ /app/docs/

RUN mkdir -p /app/results /app/data/normalized /app/data/raw && \
    chmod +x /app/fim

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
