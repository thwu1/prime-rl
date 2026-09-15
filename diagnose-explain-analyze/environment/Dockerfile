FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip graphviz sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/plans /app/output

COPY plans/ /app/plans/
COPY config.json /app/config.json
COPY manifest.json /app/manifest.json
COPY spec.json /app/spec.json

WORKDIR /app
