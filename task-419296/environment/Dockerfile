FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN cp /app/plan_ctl.py /usr/local/bin/plan-ctl && chmod +x /usr/local/bin/plan-ctl

RUN python3 /app/convert_plans.py && rm /app/convert_plans.py
RUN rm -f /app/plans/*.txt

RUN python3 /app/setup_db.py && rm /app/setup_db.py
RUN rm /app/plan_ctl.py

RUN mkdir -p /app/reports

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
