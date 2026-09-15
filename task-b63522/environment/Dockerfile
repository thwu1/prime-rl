FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y postgresql postgresql-client curl python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Install Atlas schema migration tool
RUN curl -sSf https://atlasgo.sh | sh -s -- --yes
ENV PATH="/root/.atlas/bin:${PATH}"
RUN atlas version

WORKDIR /app

# Copy Atlas configuration and migration files (agent works with these)
COPY atlas.hcl /app/atlas.hcl
COPY migrations/ /app/migrations/

# Copy build-only resources
COPY seed.sql /tmp/seed.sql
COPY drift.sql /tmp/drift.sql
COPY pg_hba.conf /tmp/pg_hba.conf
COPY setup_db.sh /tmp/setup_db.sh
RUN chmod +x /tmp/setup_db.sh

# Run database setup during build: creates atlas user, databases,
# applies first 2 migrations, seeds data, partially fails migration 3,
# and applies unauthorized schema drift.
RUN /tmp/setup_db.sh

# Clean up build-only resources to prevent answer leakage
RUN rm -f /tmp/seed.sql /tmp/drift.sql /tmp/pg_hba.conf /tmp/setup_db.sh

# Copy runtime startup script (just starts PostgreSQL)
COPY start.sh /start.sh
RUN chmod +x /start.sh

ENTRYPOINT ["/start.sh"]
CMD ["bash"]
