FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    bind9-utils \
    haproxy \
    apache2 \
    openssl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# named-checkconf validates the directory option; create it since bind9-utils
# does not ship /var/cache/bind (only the full bind9 package does)
RUN mkdir -p /var/cache/bind

# Generate self-signed SSL certificate for HAProxy TLS termination
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/server.key \
    -out /etc/ssl/certs/server.crt \
    -subj "/CN=infra.example.com" \
    && cat /etc/ssl/certs/server.crt /etc/ssl/private/server.key > /etc/ssl/private/server.pem

# Create directory structure
RUN mkdir -p /app/services/dns/zones \
    /app/services/haproxy \
    /app/services/apache/sites-available \
    /app/services/mariadb \
    /app/services/ansible \
    /var/www/html /var/www/api /var/www/admin

# Copy requirements document
COPY requirements.md /app/requirements.md

# Copy broken DNS configuration
COPY named.conf /app/services/dns/named.conf
COPY infra.example.com.zone /app/services/dns/zones/infra.example.com.zone
COPY 1.0.10.in-addr.arpa.zone /app/services/dns/zones/1.0.10.in-addr.arpa.zone

# Copy broken HAProxy configuration
COPY haproxy.cfg /app/services/haproxy/haproxy.cfg

# Copy broken Apache configurations
COPY www.conf /app/services/apache/sites-available/www.conf
COPY api.conf /app/services/apache/sites-available/api.conf
COPY admin.conf /app/services/apache/sites-available/admin.conf
COPY ports.conf /app/services/apache/ports.conf

WORKDIR /app
