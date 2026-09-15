FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.name "Test User" && \
    git config --global user.email "test@test.com" && \
    git config --global init.defaultBranch main

COPY setup_repo.py /tmp/setup_repo.py
RUN python3 /tmp/setup_repo.py && rm -f /tmp/setup_repo.py

WORKDIR /app
