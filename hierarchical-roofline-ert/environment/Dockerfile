FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

COPY data/ /app/data/

RUN mkdir -p /app/results

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
