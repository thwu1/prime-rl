
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install locales FIRST so PostgreSQL cluster gets en_US.UTF-8 collation
RUN apt-get update && apt-get install -y locales && \
    locale-gen en_US.UTF-8

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Install PostgreSQL
RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration and setup files
COPY pg_hba.conf /tmp/pg_hba.conf
COPY setup.sql /tmp/setup.sql

# Configure PostgreSQL authentication (trust for local + TCP connections)
# and populate the database with schema, data, and original function.
RUN cp /tmp/pg_hba.conf /etc/postgresql/16/main/pg_hba.conf && \
    chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf && \
    pg_ctlcluster 16 main start && \
    until pg_isready -h 127.0.0.1 -q; do sleep 1; done && \
    createdb -h 127.0.0.1 -U postgres postgres_air && \
    psql -h 127.0.0.1 -U postgres -d postgres_air -f /tmp/setup.sql && \
    pg_ctlcluster 16 main stop && \
    rm -f /var/lib/postgresql/16/main/postmaster.pid && \
    rm -f /tmp/setup.sql /tmp/pg_hba.conf

WORKDIR /app
RUN mkdir -p /app
