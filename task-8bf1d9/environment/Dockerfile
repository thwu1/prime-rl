FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS setup


RUN apt-get update && apt-get install -y \
    git \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY setup_repo.sh /tmp/setup_repo.sh
RUN chmod +x /tmp/setup_repo.sh && /tmp/setup_repo.sh

# --- Final stage: only the corrupted repo, no setup scripts ---
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY --from=setup /app/repo /app/repo

# Save original git-index-pack binary for test verification, then disable it
RUN cp /usr/lib/git-core/git-index-pack /usr/lib/git-core/.idx-pack-backup && \
    chmod 600 /usr/lib/git-core/.idx-pack-backup && \
    printf '#!/bin/sh\necho "git-index-pack: command not available - implement your own index generator" >&2\nexit 1\n' > /usr/lib/git-core/git-index-pack && \
    chmod +x /usr/lib/git-core/git-index-pack

WORKDIR /app
