FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        gcc \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY app/ /app/

WORKDIR /app
