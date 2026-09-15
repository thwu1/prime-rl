
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/taskdata/data

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY engine.py /opt/taskdata/engine.py
COPY spec.md /opt/taskdata/README.md

COPY init-app.sh /usr/local/bin/init-app.sh
RUN chmod +x /usr/local/bin/init-app.sh

# Populate /app/ from /opt/taskdata/
RUN mkdir -p /app/data && /usr/local/bin/init-app.sh

# Ensure data is restored on interactive shell in case /app/ is mounted over
RUN echo '/usr/local/bin/init-app.sh 2>/dev/null' >> /etc/bash.bashrc
RUN echo '/usr/local/bin/init-app.sh 2>/dev/null' >> /root/.bashrc

WORKDIR /app
