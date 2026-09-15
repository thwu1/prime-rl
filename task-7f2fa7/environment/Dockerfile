
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gnuplot \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output /app/output/plots

COPY data/synthesis_results.json /app/data/synthesis_results.json
COPY draft_analysis.py /app/draft_analysis.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
