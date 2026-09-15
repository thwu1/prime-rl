FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Allow trust authentication for local connections
RUN sed -i 's/peer/trust/g' /etc/postgresql/16/main/pg_hba.conf && \
    sed -i 's/scram-sha-256/trust/g' /etc/postgresql/16/main/pg_hba.conf

COPY schema.sql /docker-setup/schema.sql
COPY data_gen.sql /docker-setup/data_gen.sql
COPY init_indexes.sql /docker-setup/init_indexes.sql
COPY slow_function.sql /docker-setup/slow_function.sql
COPY setup_db.sh /docker-setup/setup_db.sh

RUN chmod +x /docker-setup/setup_db.sh && /docker-setup/setup_db.sh

RUN mkdir -p /app
COPY slow_function.sql /app/slow_function.sql

WORKDIR /app
