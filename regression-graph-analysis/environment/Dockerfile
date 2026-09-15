FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install networkx==3.3

WORKDIR /app

COPY pipeline/ /app/pipeline/

RUN curl -fSL -o /app/dataset.csv \
    "https://raw.githubusercontent.com/mozilla/regressors-regressions-dataset/main/dataset.csv" \
    && test $(wc -l < /app/dataset.csv) -gt 20000

RUN python3 /app/pipeline/analyzer_v1.py
RUN python3 /app/pipeline/analyzer_v2.py
RUN python3 /app/pipeline/analyzer_v3.py
RUN python3 /app/pipeline/run_comparison.py
