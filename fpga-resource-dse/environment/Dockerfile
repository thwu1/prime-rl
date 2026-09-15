FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY solutions_data.json /app/solutions_data.json
COPY resource_weights.json /app/resource_weights.json
