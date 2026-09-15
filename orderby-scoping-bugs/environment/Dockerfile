FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y postgresql postgresql-client python3-pip && rm -rf /var/lib/apt/lists/*

# Configure trust authentication for local connections
RUN sed -i 's/peer/trust/g; s/scram-sha-256/trust/g; s/md5/trust/g' /etc/postgresql/*/main/pg_hba.conf

# Copy application files
COPY schema.sql /app/schema.sql
COPY queries/ /app/queries/
COPY expected/ /app/expected/

# Initialize database with schema and data
RUN pg_ctlcluster 16 main start && \
    sleep 2 && \
    createdb -U postgres benchdb && \
    psql -U postgres -d benchdb -f /app/schema.sql && \
    pg_ctlcluster 16 main stop

WORKDIR /app
