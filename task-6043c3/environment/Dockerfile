FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    xxd \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY setup_repo.sh /tmp/setup_repo.sh
RUN chmod +x /tmp/setup_repo.sh && bash /tmp/setup_repo.sh && rm /tmp/setup_repo.sh

WORKDIR /app
