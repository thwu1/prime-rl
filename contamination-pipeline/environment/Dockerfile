FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    postgresql \
    postgresql-16-postgis-3 \
    locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Ensure PostgreSQL cluster exists (Docker builds may skip auto-creation)
RUN pg_lsclusters | grep -q "16.*main" || pg_createcluster --locale en_US.UTF-8 16 main

# Configure trust authentication for local connections
COPY pg_hba.conf /etc/postgresql/16/main/pg_hba.conf
RUN chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf

# Ensure socket directory exists with correct ownership
RUN mkdir -p /var/run/postgresql && chown postgres:postgres /var/run/postgresql

RUN mkdir -p /app/data

COPY setup_data.py /tmp/setup_data.py
COPY weather_format.txt /app/data/weather_format.txt

RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

WORKDIR /app
