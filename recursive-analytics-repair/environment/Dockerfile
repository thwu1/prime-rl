FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y postgresql postgresql-client python3-pip sudo && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY schema.sql /app/schema.sql
COPY queries.sql /app/queries.sql
