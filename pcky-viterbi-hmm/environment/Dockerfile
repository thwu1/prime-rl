
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip graphviz && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY grammar1.cfg /app/data/grammar1.cfg
COPY grammar2.cfg /app/data/grammar2.cfg
COPY hmm_model.txt /app/data/hmm_model.txt

WORKDIR /app
