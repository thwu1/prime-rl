FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip curl gcc && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain (minimal profile — just rustc + cargo)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

# Set up reference files
RUN mkdir -p /app/reference
COPY ga_reference.rs /app/reference/ga.rs
COPY test_ga.ua /app/reference/test_ga.ua
COPY ga_tool.rs /tmp/ga_tool.rs

# Compile the GA reference tool from Rust source
RUN rustc --edition 2021 /tmp/ga_tool.rs -o /app/reference/ga_tool && rm /tmp/ga_tool.rs

WORKDIR /app
