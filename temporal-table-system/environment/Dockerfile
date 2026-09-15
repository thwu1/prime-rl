FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y postgresql postgresql-contrib python3-pip sudo && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY temporal.sql /app/temporal.sql
COPY seed.sql /app/seed.sql
COPY setup.sh /app/setup.sh
RUN chmod +x /app/setup.sh
