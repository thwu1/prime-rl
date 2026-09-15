FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-contrib \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Configure trust authentication for local connections
RUN sed -i 's/peer/trust/g' /etc/postgresql/*/main/pg_hba.conf && \
    sed -i 's/scram-sha-256/trust/g' /etc/postgresql/*/main/pg_hba.conf


COPY setup.sql /app/setup.sql
COPY queries/ /app/queries/

WORKDIR /app
