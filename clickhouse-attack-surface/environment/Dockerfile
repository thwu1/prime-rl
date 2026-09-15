FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y \
    python3-pip \
    postgresql \
    postgresql-contrib \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /backups
RUN echo "backup_manifest_saas_20240601.sql.gz" > /backups/manifest.txt

COPY init.sql /tmp/init.sql
COPY setup_db.sh /tmp/setup_db.sh
RUN chmod +x /tmp/setup_db.sh && /tmp/setup_db.sh && rm -f /tmp/setup_db.sh /tmp/init.sql

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

WORKDIR /app
CMD ["/app/start.sh"]
