FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install MoonBit toolchain manually to avoid tar chmod failures in containers.
# The official install script uses "tar xf" which calls chmod() on extracted files;
# some container runtimes (overlayfs, podman) reject chmod, causing extraction failure.
# We replicate the install steps with Python tarfile (filter='data') for the core
# library, which skips permission/ownership setting entirely.
RUN mkdir -p /root/.moon/bin /root/.moon/lib \
    && curl -fsSL "https://cli.moonbitlang.com/binaries/latest/moonbit-linux-x86_64.tar.gz" -o /tmp/moonbit.tar.gz \
    && python3 -c "import tarfile; tarfile.open('/tmp/moonbit.tar.gz').extractall('/root/.moon', filter='data')" \
    && rm /tmp/moonbit.tar.gz \
    && find /root/.moon/bin -type f -exec chmod +x {} + \
    && (find /root/.moon/bin/internal -type f -exec chmod +x {} + 2>/dev/null || true) \
    && curl -fsSL "https://cli.moonbitlang.com/cores/core-latest.tar.gz" -o /tmp/core.tar.gz \
    && python3 -c "import tarfile; tarfile.open('/tmp/core.tar.gz').extractall('/root/.moon/lib', filter='data')" \
    && rm /tmp/core.tar.gz \
    && PATH="/root/.moon/bin:${PATH}" /root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --all \
    && PATH="/root/.moon/bin:${PATH}" /root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --target wasm-gc --quiet \
    && /root/.moon/bin/moon version

ENV PATH="/root/.moon/bin:${PATH}"

# Create project skeleton
RUN mkdir -p /app /opt/original_tests

COPY moon_mod.json /app/moon.mod.json

# Package config (empty JSON object is valid minimal config)
RUN echo '{}' > /app/moon.pkg.json

COPY hm_wbtest.mbt /app/hm_wbtest.mbt
COPY hm_wbtest.mbt /opt/original_tests/hm_wbtest.mbt

WORKDIR /app
