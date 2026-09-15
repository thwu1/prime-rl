FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
        make \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY reactor_specs.json /app/reactor_specs.json
COPY setup_db.py /app/setup_db.py
COPY Makefile /app/Makefile
COPY analysis.py /app/analysis.py

RUN cd /app && python3 setup_db.py
RUN cd /app && python3 analysis.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
