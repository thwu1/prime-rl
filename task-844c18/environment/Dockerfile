
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install scipy==1.14.1 numpy==2.1.3

COPY create_db.py /tmp/create_db.py
RUN python3 /tmp/create_db.py && rm /tmp/create_db.py

COPY Makefile /app/Makefile
COPY scripts /app/scripts
COPY evaluator.py /app/evaluator.py
COPY evaluator_v2.py /app/evaluator_v2.py
COPY review_summary.md /app/review_summary.md
COPY submissions /app/submissions

RUN chmod +x /app/scripts/extract_gt.py /app/scripts/normalize.sh

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.14.1 numpy==2.1.3
