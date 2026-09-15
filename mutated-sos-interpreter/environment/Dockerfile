FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip make && rm -rf /var/lib/apt/lists/*

COPY semantics.txt /app/semantics.txt
COPY syntax.txt /app/syntax.txt
COPY programs/ /app/programs/

RUN mkdir -p /app/results /app/results_standard /app/analysis

WORKDIR /app
