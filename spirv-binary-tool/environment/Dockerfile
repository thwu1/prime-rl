
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    spirv-tools \
    && rm -rf /var/lib/apt/lists/*

COPY spirv_reference.json /app/spirv_reference.json

COPY compute.spvasm /tmp/compute.spvasm
COPY multi_entry.spvasm /tmp/multi_entry.spvasm
COPY merge_a.spvasm /tmp/merge_a.spvasm
COPY merge_b.spvasm /tmp/merge_b.spvasm

RUN mkdir -p /app/modules && \
    spirv-as /tmp/compute.spvasm -o /app/modules/compute.spv && \
    spirv-as /tmp/multi_entry.spvasm -o /app/modules/multi_entry.spv && \
    spirv-as /tmp/merge_a.spvasm -o /app/modules/merge_a.spv && \
    spirv-as /tmp/merge_b.spvasm -o /app/modules/merge_b.spv && \
    rm /tmp/*.spvasm

WORKDIR /app
