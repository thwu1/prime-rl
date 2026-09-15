
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip python3-dev && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY quantlib/ /app/quantlib/
COPY spec.md /app/spec.md

WORKDIR /app
