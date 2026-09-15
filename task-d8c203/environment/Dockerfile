FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY setup.sql /tmp/setup.sql
COPY buggy_function.sql /tmp/buggy_function.sql
COPY workload.sql /app/workload.sql

# Configure trust authentication for all local connections
RUN echo "local all all trust" > /etc/postgresql/16/main/pg_hba.conf && \
    echo "host all all 127.0.0.1/32 trust" >> /etc/postgresql/16/main/pg_hba.conf && \
    echo "host all all ::1/128 trust" >> /etc/postgresql/16/main/pg_hba.conf

# Initialize database with schema and data
RUN pg_ctlcluster 16 main start && \
    pg_isready -U postgres -t 30 && \
    createdb -U postgres postgres_air && \
    psql -U postgres -d postgres_air -f /tmp/setup.sql && \
    psql -U postgres -d postgres_air -f /tmp/buggy_function.sql && \
    pg_ctlcluster 16 main stop

# Clean up setup files so function source is only in the catalog
RUN rm -f /tmp/setup.sql /tmp/buggy_function.sql

WORKDIR /app
