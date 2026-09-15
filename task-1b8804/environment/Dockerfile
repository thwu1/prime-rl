FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip graphviz sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data/levels /app/viz

COPY levels/ /data/levels/

WORKDIR /app
