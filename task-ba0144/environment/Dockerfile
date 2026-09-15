
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY pg_hba.conf /etc/postgresql/16/main/pg_hba.conf
RUN chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf && \
    mkdir -p /var/run/postgresql && chown postgres:postgres /var/run/postgresql && \
    mkdir -p /var/log/postgresql && chown postgres:postgres /var/log/postgresql && \
    chmod 1777 /tmp

COPY init_schema.sql /tmp/init_schema.sql
COPY init_data.sql /tmp/init_data.sql
COPY setup_db.sh /tmp/setup_db.sh
RUN chmod +x /tmp/setup_db.sh

RUN /tmp/setup_db.sh

# Ensure no stale PID or socket files survive into the image
RUN rm -f /var/lib/postgresql/16/main/postmaster.pid \
          /var/run/postgresql/16-main.pid \
          /var/run/postgresql/.s.PGSQL.*

RUN mkdir -p /app
WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
