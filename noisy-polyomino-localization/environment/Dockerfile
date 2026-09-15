FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    postgresql \
    postgresql-client \
    gnuplot \
    jq \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Configure PostgreSQL for trust authentication (local connections)
RUN find /etc/postgresql -name pg_hba.conf -exec sed -i 's/peer/trust/g' {} \; && \
    find /etc/postgresql -name pg_hba.conf -exec sed -i 's/scram-sha-256/trust/g' {} \;

WORKDIR /app

# Compile oracle server from C source, then delete source
COPY engine.c /tmp/engine.c
RUN gcc -O2 -o /app/poly_server /tmp/engine.c -lm && \
    rm -f /tmp/engine.c && \
    chmod +x /app/poly_server

COPY protocol.txt /app/PROTOCOL.txt
COPY schema.sql /app/schema.sql
