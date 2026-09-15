
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app

COPY physics.py /app/physics.py
COPY methods.py /app/methods.py
COPY benchmark.py /app/benchmark.py

WORKDIR /app
