FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    default-jdk-headless \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY build.sh /app/build.sh
COPY src/ /app/src/
COPY data/ /app/data/

RUN chmod +x /app/build.sh

WORKDIR /app
