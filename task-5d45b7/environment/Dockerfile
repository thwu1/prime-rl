FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data/problems /app

COPY problems/ROSENBR.SIF /data/problems/ROSENBR.SIF
COPY problems/HS71.SIF /data/problems/HS71.SIF
COPY problems/BENCHOPT.SIF /data/problems/BENCHOPT.SIF

RUN ls -la /data/problems/ && wc -l /data/problems/*.SIF

RUN ln -sf /data/problems /app/problems

WORKDIR /app
