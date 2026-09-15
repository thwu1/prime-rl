FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip curl nginx postgresql postgresql-contrib && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==3.1.1 psycopg2-binary==2.9.10

COPY pg_hba.conf /etc/postgresql/16/main/pg_hba.conf
RUN chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf && chmod 640 /etc/postgresql/16/main/pg_hba.conf

COPY buggy_nginx.conf /etc/nginx/sites-enabled/cds-proxy
RUN rm -f /etc/nginx/sites-enabled/default

COPY data/ /app/data/
COPY buggy_server.py /app/server.py
COPY buggy_engine.py /app/interaction_engine.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 requests==2.32.3
