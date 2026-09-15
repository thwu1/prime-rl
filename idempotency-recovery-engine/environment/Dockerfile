FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y postgresql python3 python3-pip python3-dev build-essential sudo && \
    rm -rf /var/lib/apt/lists/*

# Ensure /etc/passwd is world-readable so UID lookups work in container runtimes
RUN chmod 644 /etc/passwd

# Configure PostgreSQL for trust authentication (no passwords)
COPY pg_hba.conf /etc/postgresql/16/main/pg_hba.conf
RUN chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf

# Ensure PostgreSQL listens on TCP localhost
RUN echo "listen_addresses = 'localhost'" >> /etc/postgresql/16/main/postgresql.conf

# Copy application files
COPY schema.sql /app/schema.sql
COPY config.py /app/config.py
COPY idempotency_buggy.py /app/idempotency.py

# Make all files in /app readable
RUN chmod -R a+rX /app

# Pre-initialize the database during build
RUN mkdir -p /var/run/postgresql && \
    chown postgres:postgres /var/run/postgresql && \
    pg_ctlcluster 16 main start && \
    su postgres -c "createdb idempotency" && \
    su postgres -c "psql -d idempotency -f /app/schema.sql" && \
    pg_ctlcluster 16 main stop

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 psycopg2-binary==2.9.10
