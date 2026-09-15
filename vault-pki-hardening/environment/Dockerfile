FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    curl \
    jq \
    openssl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN VAULT_VERSION="1.15.6" && \
    curl -fsSL "https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_linux_amd64.zip" -o /tmp/vault.zip && \
    unzip /tmp/vault.zip -d /usr/local/bin/ && \
    rm /tmp/vault.zip && \
    chmod +x /usr/local/bin/vault

RUN mkdir -p /app/vault-data /app/vault-creds /app/certs /var/log/vault

COPY vault-config.hcl /app/vault-config.hcl
COPY remediation-requirements.txt /app/remediation-requirements.txt
COPY setup-broken-state.sh /tmp/setup-broken-state.sh

RUN chmod +x /tmp/setup-broken-state.sh && bash /tmp/setup-broken-state.sh && rm /tmp/setup-broken-state.sh

WORKDIR /app
