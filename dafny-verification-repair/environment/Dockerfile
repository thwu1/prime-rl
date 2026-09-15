FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    python3-pip \
    libicu-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Dafny 4.4.0 (self-contained release with bundled .NET runtime and Z3)
ENV DAFNY_VERSION=4.4.0
RUN wget -q "https://github.com/dafny-lang/dafny/releases/download/v${DAFNY_VERSION}/dafny-${DAFNY_VERSION}-x64-ubuntu-20.04.zip" -O /tmp/dafny.zip && \
    unzip -q /tmp/dafny.zip -d /opt && \
    rm /tmp/dafny.zip && \
    chmod -R +x /opt/dafny

ENV PATH="/opt/dafny:${PATH}"

# Copy Dafny programs with verification annotations removed
COPY sel_sort.dfy /app/sel_sort.dfy
COPY insertion_sort.dfy /app/insertion_sort.dfy
COPY seq_max_sum.dfy /app/seq_max_sum.dfy

# Store originals for anti-cheat comparison
RUN mkdir -p /app/.originals && \
    cp /app/sel_sort.dfy /app/.originals/ && \
    cp /app/insertion_sort.dfy /app/.originals/ && \
    cp /app/seq_max_sum.dfy /app/.originals/

WORKDIR /app
