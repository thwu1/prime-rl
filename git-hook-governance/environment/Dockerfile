FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y git python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git config --global user.email "test@example.com" && \
    git config --global user.name "Test User" && \
    git config --global init.defaultBranch main

RUN mkdir -p /app/hooks
COPY pre-receive.sh /app/hooks/pre-receive
RUN chmod +x /app/hooks/pre-receive

