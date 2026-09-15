
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/submissions /app/evaluator

COPY data/golden.json /app/data/golden.json
COPY data/submissions/system_alpha.json /app/data/submissions/system_alpha.json
COPY data/submissions/system_beta.json /app/data/submissions/system_beta.json
COPY data/submissions/system_gamma.json /app/data/submissions/system_gamma.json
COPY data/submissions/system_delta.json /app/data/submissions/system_delta.json
COPY data/submissions/system_epsilon.json /app/data/submissions/system_epsilon.json
COPY spec.md /app/spec.md
COPY evaluator/evaluate.py /app/evaluator/evaluate.py
COPY create_db.py /tmp/create_db.py

RUN python3 /tmp/create_db.py
RUN python3 /app/evaluator/evaluate.py

WORKDIR /app
