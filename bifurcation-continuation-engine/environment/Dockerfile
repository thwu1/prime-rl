FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip build-essential gnuplot-nox && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY systems.py /app/systems.py
COPY rhs_eval.c /app/rhs_eval.c

WORKDIR /app
