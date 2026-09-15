FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y default-jdk make python3-pip graphviz && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY tac/ /app/tac/
COPY Makefile /app/Makefile

RUN mkdir -p /app/build

WORKDIR /app
