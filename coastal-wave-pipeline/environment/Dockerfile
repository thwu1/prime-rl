FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc make gawk sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/scenarios /app/data/cem_reference /app/raw_surveys /app/src /app/lib

COPY scenarios/ /app/scenarios/
COPY data/ /app/data/
COPY raw_surveys/ /app/raw_surveys/

WORKDIR /app
