FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc make binutils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec /app/scenarios

COPY spec/ /app/spec/
COPY scenarios/ /app/scenarios/

WORKDIR /app
