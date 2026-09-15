FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
    apache2 \
    python3-pip \
    yara \
    curl \
    jq \
    && a2enmod rewrite proxy proxy_http headers \
    && (a2dismod -f deflate 2>/dev/null || true) \
    && echo "ServerName localhost" >> /etc/apache2/apache2.conf \
    && mkdir -p /var/run/apache2 /var/lock/apache2 \
    && rm -rf /var/lib/apt/lists/*

# Broken Apache VirtualHost config with incorrect C2 redirector rules
COPY broken_vhost.conf /etc/apache2/sites-available/000-default.conf

# Generate task environment (profiles, samples, traffic logs)
COPY setup_task.py /tmp/setup_task.py
RUN python3 /tmp/setup_task.py && rm /tmp/setup_task.py

WORKDIR /app
