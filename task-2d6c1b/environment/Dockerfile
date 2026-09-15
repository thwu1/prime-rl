FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /opt/generate_data.py
RUN python3 /opt/generate_data.py && \
    test -f /opt/taskdata/taxonomy/nodes.dmp && \
    test -f /opt/taskdata/taxonomy/names.dmp && \
    test -f /opt/taskdata/taxonomy/merged.dmp && \
    test -f /opt/taskdata/gold_standard.profile && \
    test -d /opt/taskdata/submissions && \
    echo "Data generation verified OK"

WORKDIR /app
