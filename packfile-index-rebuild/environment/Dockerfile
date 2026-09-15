FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    xxd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY generate_manifest.py /tmp/generate_manifest.py
COPY setup_repo.sh /tmp/setup_repo.sh
RUN chmod +x /tmp/setup_repo.sh && /tmp/setup_repo.sh && rm /tmp/setup_repo.sh /tmp/generate_manifest.py
