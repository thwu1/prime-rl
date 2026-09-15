FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip curl jq && rm -rf /var/lib/apt/lists/*

RUN curl -fL --retry 3 -o /usr/local/bin/opa \
    https://github.com/open-policy-agent/opa/releases/download/v0.70.0/opa_linux_amd64_static && \
    chmod +x /usr/local/bin/opa && \
    opa version

COPY rego/ /app/rego/
COPY target_outcomes.json /app/target_outcomes.json

WORKDIR /app
