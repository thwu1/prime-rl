FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pools/ /app/pools/

COPY oracle_setup.sql /tmp/oracle_setup.sql
RUN sqlite3 /app/oracle.db < /tmp/oracle_setup.sql && rm /tmp/oracle_setup.sql

COPY ref_reconstruct.py /tmp/ref_src.py
COPY ref_wrapper.sh /app/pool_ref
RUN chmod +x /app/pool_ref && \
    python3 -m py_compile /tmp/ref_src.py && \
    cp /tmp/__pycache__/ref_src.cpython-*.pyc /app/_ref.pyc && \
    rm -rf /tmp/ref_src.py /tmp/__pycache__
