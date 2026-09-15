FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY app/ /app/

# Make cfctl executable and add to PATH
RUN chmod +x /app/cfctl
ENV PATH="/app:${PATH}"

# Initialize database shards, config history
RUN python3 /app/setup_db.py

# Generate initial feature file from a migrated shard
# This produces the "bad" feature file with 226 features (doubled)
RUN python3 /app/generator/generate.py /app/db/shards/shard_0.db

WORKDIR /app
