FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y curl git python3-pip build-essential && rm -rf /var/lib/apt/lists/*

# Install Lean 4.16.0 directly from release (no elan dependency)
RUN curl -sL "https://github.com/leanprover/lean4/releases/download/v4.16.0/lean-4.16.0-linux.zip" -o /tmp/lean.zip && \
    python3 -c "import zipfile; zipfile.ZipFile('/tmp/lean.zip').extractall('/opt')" && \
    chmod -R +x /opt/lean-4.16.0-linux/bin/ && \
    rm /tmp/lean.zip

ENV PATH="/opt/lean-4.16.0-linux/bin:${PATH}"

# Verify lean and lake are accessible
RUN lean --version && lake --version

WORKDIR /app

COPY lakefile.toml /app/lakefile.toml
COPY Reduction.lean /app/Reduction.lean
