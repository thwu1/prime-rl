FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py
RUN rm -f /tmp/setup_data.py
RUN test -f /opt/semtab_data/config.json && \
    test -f /opt/semtab_data/gold/cea.csv && \
    test -f /opt/semtab_data/ontology/type_hierarchy.ttl && \
    echo "All data files verified"

WORKDIR /app
