FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip curl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /tmp/hl && \
    curl -fsSL -o /tmp/hl/hl.tar.gz \
      https://github.com/simonmichael/hledger/releases/latest/download/hledger-linux-x64.tar.gz && \
    tar xzf /tmp/hl/hl.tar.gz -C /tmp/hl && \
    find /tmp/hl -name 'hledger' -type f | head -1 | xargs -I{} cp {} /usr/local/bin/hledger && \
    chmod +x /usr/local/bin/hledger && \
    rm -rf /tmp/hl && \
    hledger --version

COPY transactions.csv /app/transactions.csv

WORKDIR /app
