FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /app

COPY app/catalog.json /data/catalog.json
COPY app/case.json /data/case.json
COPY app/rubric.json /data/rubric.json
COPY app/models.py /app/models.py
COPY app/runner.py /app/runner.py
COPY app/order_matcher.py /app/order_matcher.py
COPY app/simulation.py /app/simulation.py
COPY app/scorer.py /app/scorer.py

WORKDIR /app
