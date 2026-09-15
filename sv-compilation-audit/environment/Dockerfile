FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pre-built slang SystemVerilog compiler (v11.0)
RUN curl -sL https://github.com/MikePopoloski/slang/releases/download/v11.0/slang-linux-x86_64.tar.gz \
    -o /tmp/slang.tar.gz && \
    tar xzf /tmp/slang.tar.gz -C /usr/local/bin/ && \
    chmod +x /usr/local/bin/slang && \
    rm /tmp/slang.tar.gz

# Copy the SystemVerilog design files and specification
COPY design/ /app/design/

WORKDIR /app
