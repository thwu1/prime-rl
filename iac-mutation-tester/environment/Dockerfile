FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L -o /usr/local/bin/opa https://github.com/open-policy-agent/opa/releases/download/v0.64.1/opa_linux_amd64_static && \
    chmod +x /usr/local/bin/opa

RUN mkdir -p /app/scenarios/vpc_network /app/scenarios/dns_loadbalancer /app/scenarios/iam_permissions /app/mutester

COPY scenarios/vpc_network/plan.json /app/scenarios/vpc_network/plan.json
COPY scenarios/vpc_network/policy.rego /app/scenarios/vpc_network/policy.rego
COPY scenarios/dns_loadbalancer/plan.json /app/scenarios/dns_loadbalancer/plan.json
COPY scenarios/dns_loadbalancer/policy.rego /app/scenarios/dns_loadbalancer/policy.rego
COPY scenarios/iam_permissions/plan.json /app/scenarios/iam_permissions/plan.json
COPY scenarios/iam_permissions/policy.rego /app/scenarios/iam_permissions/policy.rego

WORKDIR /app
