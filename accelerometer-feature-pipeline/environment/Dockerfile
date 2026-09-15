FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV LANG=C.UTF-8


RUN apt-get update && \
    apt-get install -y openjdk-17-jdk python3-pip make && \
    rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY Makefile /app/Makefile
COPY config/ /app/config/

WORKDIR /app
