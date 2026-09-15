FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    sipcalc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/registry

COPY setup_repo.sh /tmp/setup_repo.sh
COPY stages/ /tmp/stages/
RUN chmod +x /tmp/setup_repo.sh && /tmp/setup_repo.sh && rm -rf /tmp/stages /tmp/setup_repo.sh

WORKDIR /app
