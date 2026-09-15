FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip libxml2-utils xmlstarlet sqlite3 && rm -rf /var/lib/apt/lists/*

COPY baxter.urdf /app/baxter.urdf
COPY task_config.toml /app/task_config.toml

WORKDIR /app
