FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Prevent services from auto-starting during apt-get install
RUN echo '#!/bin/sh\nexit 101' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d

# Install BIND9 DNS server and diagnostic utilities
RUN apt-get update && \
    apt-get install -y bind9 bind9-utils dnsutils python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Remove the auto-start blocker so named can be started manually
RUN rm -f /usr/sbin/policy-rc.d

# Ensure named is stopped and not enabled
RUN pkill named 2>/dev/null || true

# Create zones directory and runtime directories
RUN mkdir -p /etc/bind/zones /run/named /var/cache/bind

# Copy working (unsecured) configuration files
COPY bind-config/named.conf /etc/bind/named.conf
COPY bind-config/named.conf.options /etc/bind/named.conf.options
COPY bind-config/named.conf.local /etc/bind/named.conf.local
COPY bind-config/acl.conf /etc/bind/acl.conf
COPY bind-config/zones/db.weilburg.corp /etc/bind/zones/db.weilburg.corp
COPY bind-config/zones/db.weilburg.corp.external /etc/bind/zones/db.weilburg.corp.external
COPY bind-config/zones/db.10.10.0 /etc/bind/zones/db.10.10.0

# Set proper ownership for BIND to read configs and write cache/runtime
RUN chown -R root:bind /etc/bind && \
    find /etc/bind -type f -exec chmod 644 {} \; && \
    find /etc/bind -type d -exec chmod 755 {} \; && \
    chown -R bind:bind /var/cache/bind /run/named

# Working directory
RUN mkdir -p /app
WORKDIR /app
