FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==3.0.3 pyyaml==6.0.1

COPY waf_rules.yaml /app/waf_rules.yaml
COPY waf.py /app/waf.py
COPY server.py /app/server.py
COPY test_legitimate.py /app/test_legitimate.py
COPY start_service.sh /app/start_service.sh
COPY init_db.py /tmp/init_db.py

RUN chmod +x /app/start_service.sh
RUN mkdir -p /var/log/waf
RUN python3 /tmp/init_db.py && rm /tmp/init_db.py

WORKDIR /app
