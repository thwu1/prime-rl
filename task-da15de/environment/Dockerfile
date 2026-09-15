FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip golang-go git curl jq \
    && rm -rf /var/lib/apt/lists/*

# Install fzf binary (specific version for reproducibility)
RUN curl -fsSL https://github.com/junegunn/fzf/releases/download/v0.57.0/fzf-0.57.0-linux_amd64.tar.gz \
    | tar xz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/fzf

RUN mkdir -p /app
WORKDIR /app
