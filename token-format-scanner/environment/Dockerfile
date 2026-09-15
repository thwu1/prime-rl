FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip git sqlite3 openssl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/corpus /app/audit

COPY spec.md /app/spec.md
COPY known_valid.json /app/known_valid.json

COPY corpus/app.py /app/corpus/app.py
COPY corpus/config.yaml /app/corpus/config.yaml
COPY corpus/env_file /app/corpus/.env
COPY corpus/secrets.json /app/corpus/secrets.json
COPY corpus/access.log /app/corpus/access.log
COPY corpus/deploy.sh /app/corpus/deploy.sh
COPY corpus/terraform.tf /app/corpus/terraform.tf
COPY corpus/docker-compose.yml /app/corpus/docker-compose.yml
COPY corpus/notebook.sql /app/corpus/notebook.sql

COPY setup_vault.sh /tmp/setup_vault.sh
RUN chmod +x /tmp/setup_vault.sh && /tmp/setup_vault.sh && rm /tmp/setup_vault.sh

COPY setup_git_repo.sh /tmp/setup_git_repo.sh
RUN chmod +x /tmp/setup_git_repo.sh && /tmp/setup_git_repo.sh && rm /tmp/setup_git_repo.sh

COPY setup_audit_db.py /tmp/setup_audit_db.py
RUN python3 /tmp/setup_audit_db.py && rm /tmp/setup_audit_db.py

WORKDIR /app
