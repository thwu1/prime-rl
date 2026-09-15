FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /app /tmp/archive

# Create SQLite database (policy, expense, reinsurance data)
COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /data/portfolio.db < /tmp/init_db.sql && rm /tmp/init_db.sql

# Bundle actuarial assumptions into compressed archive
COPY valuation.toml /tmp/archive/valuation.toml
COPY mortality.yaml /tmp/archive/mortality.yaml
RUN cd /tmp/archive && tar -czf /data/assumptions.tar.gz valuation.toml mortality.yaml && rm -rf /tmp/archive

WORKDIR /app
