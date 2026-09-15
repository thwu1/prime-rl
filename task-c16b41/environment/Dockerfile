FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install yq v4 (Go-based YAML processor by Mike Farah)
RUN curl -fsSL https://github.com/mikefarah/yq/releases/download/v4.44.1/yq_linux_amd64 \
    -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq

RUN mkdir -p /app/configs /app/docs

COPY files/models.json /app/models.json
COPY files/manifest.yaml /app/manifest.yaml
COPY files/configs/broken_1.yaml /app/configs/broken_1.yaml
COPY files/configs/broken_2.yaml /app/configs/broken_2.yaml
COPY files/configs/broken_3.yaml /app/configs/broken_3.yaml
COPY files/configs/broken_4.yaml /app/configs/broken_4.yaml
COPY files/configs/broken_5.yaml /app/configs/broken_5.yaml
COPY files/configs/reference_300b_fp8.yaml /app/configs/reference_300b_fp8.yaml
COPY files/configs/reference_03b_bf16.yaml /app/configs/reference_03b_bf16.yaml
COPY files/docs/api_contract.md /app/docs/api_contract.md
COPY files/docs/memory_model.md /app/docs/memory_model.md
COPY files/docs/erniekit_reference.md /app/docs/erniekit_reference.md

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pyyaml==6.0.2
