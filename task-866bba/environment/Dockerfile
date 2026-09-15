FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl \
    jq \
    openssl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install cosign v2.4.0
RUN curl -sSfL --retry 3 -o /usr/local/bin/cosign \
    "https://github.com/sigstore/cosign/releases/download/v2.4.0/cosign-linux-amd64" && \
    chmod +x /usr/local/bin/cosign

# Create directory structure
RUN mkdir -p /app/build_output /app/artifacts /app/keys /app/bundles /app/attestations

# Create canonical build outputs (original release artifacts)
RUN printf 'api-server-binary-v1.0.0-release-20240601-x86_64-linux-gnu-a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6' > /app/build_output/api-server.bin && \
    printf 'auth-module-binary-v2.1.0-release-20240601-x86_64-linux-gnu-e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0' > /app/build_output/auth-module.bin && \
    printf 'data-pipeline-binary-v3.0.1-release-20240601-x86_64-linux-gnu-u1v2w3x4y5z6a7b8c9d0e1f2g3h4i5j6' > /app/build_output/data-pipeline.bin && \
    printf 'crypto-lib-binary-v1.5.0-release-20240601-x86_64-linux-gnu-k7l8m9n0o1p2q3r4s5t6u7v8w9x0y1z2' > /app/build_output/crypto-lib.bin && \
    printf 'monitoring-agent-binary-v0.9.0-release-20240601-x86_64-linux-gnu-a3b4c5d6e7f8g9h0i1j2k3l4m5n6o7p8' > /app/build_output/monitoring-agent.bin

# Deploy artifacts (copy from build output to deployment location)
RUN cp /app/build_output/*.bin /app/artifacts/

# Simulate post-deployment compromise on one artifact
RUN printf 'TAMPERED' >> /app/artifacts/data-pipeline.bin

# Install signing policy
COPY policy.json /app/policy.json

# Install initial (broken) verification script and generate its report
COPY broken_verify.sh /app/verify.sh
RUN chmod +x /app/verify.sh && /app/verify.sh

WORKDIR /app
