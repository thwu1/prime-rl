FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Remove policy-rc.d so 'service postgresql start' works at runtime
RUN rm -f /usr/sbin/policy-rc.d

COPY setup.sql /tmp/setup.sql
COPY configure_hba.sh /tmp/configure_hba.sh
RUN chmod +x /tmp/configure_hba.sh && /tmp/configure_hba.sh

COPY init_db.sh /tmp/init_db.sh
RUN chmod +x /tmp/init_db.sh && /tmp/init_db.sh

RUN mkdir -p /app/queries
COPY Q1.sql /app/queries/Q1.sql
COPY Q2.sql /app/queries/Q2.sql
COPY Q3.sql /app/queries/Q3.sql
COPY Q4.sql /app/queries/Q4.sql
COPY Q5.sql /app/queries/Q5.sql

WORKDIR /app
