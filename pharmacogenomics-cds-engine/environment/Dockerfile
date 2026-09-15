FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-psycopg2 \
    jq \
    sqlite3 \
    postgresql \
    && rm -rf /var/lib/apt/lists/*

# Configure PostgreSQL for local trust authentication (no password)
RUN sed -i 's/peer/trust/g' /etc/postgresql/16/main/pg_hba.conf && \
    sed -i 's/scram-sha-256/trust/g' /etc/postgresql/16/main/pg_hba.conf

RUN mkdir -p /app/data

COPY data/alleles.json /app/data/alleles.json
COPY data/diplotypes.json /app/data/diplotypes.json
COPY data/recommendations.json /app/data/recommendations.json
COPY data/drugs.json /app/data/drugs.json
COPY data/gene_results.json /app/data/gene_results.json
COPY data/pairs.json /app/data/pairs.json
COPY data/cpic_supplement.sql /app/data/cpic_supplement.sql


WORKDIR /app
