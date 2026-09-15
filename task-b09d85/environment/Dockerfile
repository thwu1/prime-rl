FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    curl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSf https://atlasgo.sh | sh

RUN sed -i 's/peer/trust/g; s/scram-sha-256/trust/g; s/md5/trust/g' /etc/postgresql/16/main/pg_hba.conf
RUN echo "listen_addresses = 'localhost'" >> /etc/postgresql/16/main/postgresql.conf

COPY migrations_setup/ /app/migrations/
COPY atlas.hcl /app/atlas.hcl
COPY seed_data.sql /app/seed_data.sql
COPY product_categories.sql /app/product_categories.sql
COPY operator_fix.sql /app/operator_fix.sql
COPY setup.sh /app/setup.sh
RUN chmod +x /app/setup.sh

RUN /app/setup.sh

COPY migrations_extra/20240101000004_reviews.sql /app/migrations/20240101000004_reviews.sql
COPY migrations_extra/20240101000004_reviews_and_phone.sql /app/migrations/20240101000004_reviews_and_phone.sql
COPY migrations_extra/20240101000005_catalog_constraints.sql /app/migrations/20240101000005_catalog_constraints.sql

RUN rm -f /app/migrations/atlas.sum

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
