FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gdal-bin python3-gdal python3-numpy python3-pip proj-data && \
    rm -rf /var/lib/apt/lists/*

# Generate task data to a persistent location (not /app/ which may be a VOLUME)
COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

# Set up init script to populate /app/ at runtime
COPY init_data.sh /usr/local/bin/init_data.sh
RUN chmod +x /usr/local/bin/init_data.sh

# Ensure data is copied to /app/ on interactive shell start
RUN echo '/usr/local/bin/init_data.sh' >> /root/.bashrc

# Also try to pre-populate /app/ (works if /app/ is not a volume)
RUN mkdir -p /app/output && cp /opt/task_data/* /app/ 2>/dev/null || true

WORKDIR /app
