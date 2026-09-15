FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 golang-go cargo rustc gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy prefix data
COPY data/prefixes.json /app/data/prefixes.json

# Set up the database with dual-schema feature metadata
COPY db_setup.py /app/db_setup.py
RUN python3 /app/db_setup.py

# Copy config generator source
COPY configgen/ /app/configgen/

# Copy Go prefix manager source
COPY prefixmgr/ /app/prefixmgr/

# Copy Rust config loader source
COPY loader/ /app/loader/

# Build Go prefix manager binary
RUN mkdir -p /app/bin && cd /app/prefixmgr && go build -o /app/bin/prefixmgr .

# Build Rust config loader binary (downloads serde crates)
RUN cd /app/loader && cargo build --release && cp target/release/config_loader /app/bin/config_loader

# Generate initial (buggy) feature config so the agent can inspect it
RUN mkdir -p /app/config && python3 /app/configgen/generate.py
