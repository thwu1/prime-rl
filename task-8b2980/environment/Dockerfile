FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY lib.py /app/lib.py
COPY dtrain /app/dtrain
COPY setup_db.py /app/setup_db.py
COPY Makefile /app/Makefile

RUN chmod +x /app/dtrain
RUN cd /app && python3 setup_db.py && rm setup_db.py

WORKDIR /app
