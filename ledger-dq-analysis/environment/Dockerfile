FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
COPY generate_data.py /tmp/gen.py
RUN python3 /tmp/gen.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    postgresql \
    postgresql-client \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Fix NSS: remove systemd backend that fails in podman builds
RUN sed -i 's/ systemd//' /etc/nsswitch.conf || true

# Configure trust auth before starting PostgreSQL
RUN echo "local all all trust" > /etc/postgresql/16/main/pg_hba.conf && \
    echo "host all all 127.0.0.1/32 trust" >> /etc/postgresql/16/main/pg_hba.conf && \
    echo "host all all ::1/128 trust" >> /etc/postgresql/16/main/pg_hba.conf

COPY --from=builder /generated/config/ /app/config/
COPY --from=builder /generated/data/bank_settlements.csv /app/data/bank_settlements.csv
COPY --from=builder /generated/data/events.csv /tmp/events.csv
COPY init_db.sql /tmp/init_db.sql

# Use TCP connection as root to avoid su/NSS user-switch issues in podman
RUN pg_ctlcluster 16 main start && \
    sleep 1 && \
    createuser -U postgres -h 127.0.0.1 ledger && \
    createdb -U postgres -h 127.0.0.1 ledger -O ledger && \
    psql -U postgres -h 127.0.0.1 -d ledger -f /tmp/init_db.sql && \
    rm -f /tmp/events.csv /tmp/init_db.sql && \
    pg_ctlcluster 16 main stop

WORKDIR /app
