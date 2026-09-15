FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip openssl sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==42.0.8 msgpack==1.0.8

RUN mkdir -p /app/macaroon /app/pki /app/tkdb

COPY macaroon_lib.py /app/macaroon/__init__.py
COPY requirements.md /app/REQUIREMENTS.md
COPY design_candidates.md /app/DESIGN_CANDIDATES.md
COPY draft_service.py /app/tkdb/draft_service.py

ENV PYTHONPATH=/app
WORKDIR /app
