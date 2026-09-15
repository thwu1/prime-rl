FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip curl build-essential && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Generate JSON-format problem instances
COPY gen_instances.py /tmp/gen_instances.py
RUN python3 /tmp/gen_instances.py && rm /tmp/gen_instances.py

# Generate text-format instances that require conversion
COPY gen_text_instances.py /tmp/gen_text_instances.py
RUN python3 /tmp/gen_text_instances.py && rm /tmp/gen_text_instances.py

# Set up Rust format converter
RUN mkdir -p /app/converter/src
COPY converter_cargo.toml /app/converter/Cargo.toml
COPY converter_main.rs /app/converter/src/main.rs

# Build and run converter on text instances
RUN cd /app/converter && cargo build --release 2>&1 && \
    ./target/release/ising-converter /app/instances/raw /app/instances || true

# Install candidate solver implementations
RUN mkdir -p /app/solvers
COPY solver_alpha.py /app/solvers/alpha.py
COPY solver_beta.py /app/solvers/beta.py
COPY solver_gamma.py /app/solvers/gamma.py

# Solver configuration
COPY config.toml /app/config.toml

RUN mkdir -p /app/results
