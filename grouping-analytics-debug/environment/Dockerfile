FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN echo "local all all trust" > /etc/postgresql/16/main/pg_hba.conf && \
    echo "host all all 127.0.0.1/32 trust" >> /etc/postgresql/16/main/pg_hba.conf && \
    echo "host all all ::1/128 trust" >> /etc/postgresql/16/main/pg_hba.conf && \
    sed -i "s/^#listen_addresses = .*/listen_addresses = 'localhost'/" /etc/postgresql/16/main/postgresql.conf

WORKDIR /app

COPY setup.sql /app/setup.sql
COPY analytics.sql /app/analytics.sql

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 psycopg2-binary==2.9.9
