FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y openjdk-21-jdk python3-pip wget && \
    rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY events/ /app/events/

RUN mkdir -p /app/lib /app/build

WORKDIR /app
