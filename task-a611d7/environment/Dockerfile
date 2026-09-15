FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-full graphviz jq curl && \
    rm -rf /var/lib/apt/lists/*

RUN BUILDTOOLS_VERSION="8.5.1" && \
    curl -fsSL -o /usr/local/bin/buildozer \
    "https://github.com/bazelbuild/buildtools/releases/download/v${BUILDTOOLS_VERSION}/buildozer-linux-amd64" && \
    chmod +x /usr/local/bin/buildozer && \
    curl -fsSL -o /usr/local/bin/buildifier \
    "https://github.com/bazelbuild/buildtools/releases/download/v${BUILDTOOLS_VERSION}/buildifier-linux-amd64" && \
    chmod +x /usr/local/bin/buildifier

WORKDIR /app

COPY generate_monorepo.py /tmp/generate_monorepo.py
RUN python3 /tmp/generate_monorepo.py && rm /tmp/generate_monorepo.py

COPY depcheck.py /app/depcheck.py
