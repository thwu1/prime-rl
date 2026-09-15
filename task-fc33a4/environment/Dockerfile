FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.email "bench@test.com" && \
    git config --global user.name "Bench"

COPY setup_repo.py /tmp/setup_repo.py
RUN python3 /tmp/setup_repo.py && rm /tmp/setup_repo.py

WORKDIR /app
