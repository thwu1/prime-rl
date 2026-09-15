FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV HOME=/root
ENV ELAN_HOME=/root/.elan
ENV PATH="/root/.elan/bin:/usr/local/bin:${PATH}"


RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install elan (Lean 4 version manager)
RUN curl -fL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh && \
    bash /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:v4.12.0 && \
    rm /tmp/elan-init.sh

# Symlink elan shims into /usr/local/bin and verify toolchain works
RUN ln -sf /root/.elan/bin/lean /usr/local/bin/lean && \
    ln -sf /root/.elan/bin/lake /usr/local/bin/lake && \
    ln -sf /root/.elan/bin/leanc /usr/local/bin/leanc && \
    ln -sf /root/.elan/bin/elan /usr/local/bin/elan && \
    chmod a+rx /root && \
    chmod -R a+rX /root/.elan && \
    lean --version && \
    lake --version

# Set up project
WORKDIR /app
COPY lakefile.lean /app/lakefile.lean
COPY lean-toolchain /app/lean-toolchain
COPY VerifiedListOps.lean /app/VerifiedListOps.lean

# Pre-build to cache compilation artifacts (succeeds with sorry warnings)
RUN lake build
