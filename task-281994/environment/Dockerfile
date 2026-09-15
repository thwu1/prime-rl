FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip fzf golang-go && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/fzf-src/src
COPY algo.go /app/fzf-src/src/algo.go
COPY algo_test.go /app/fzf-src/src/algo_test.go

COPY scaffold.py /app/fzf_scorer.py
WORKDIR /app
