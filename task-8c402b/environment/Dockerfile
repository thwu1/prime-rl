FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    redis-server \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

COPY valkey.conf /app/valkey.conf
COPY generate_data.sh /setup/generate_data.sh
RUN chmod +x /setup/generate_data.sh && /setup/generate_data.sh
