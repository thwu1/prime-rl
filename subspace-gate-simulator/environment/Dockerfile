FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip curl && rm -rf /var/lib/apt/lists/*

# Install Julia 1.10
RUN curl -fsSL https://julialang-s3.julialang.org/bin/linux/x64/1.10/julia-1.10.0-linux-x86_64.tar.gz -o /tmp/julia.tar.gz && \
    tar xzf /tmp/julia.tar.gz -C /opt/ && \
    ln -s /opt/julia-1.10.0/bin/julia /usr/local/bin/julia && \
    rm /tmp/julia.tar.gz

# Set Julia depot path explicitly so packages are found at runtime regardless of HOME
ENV JULIA_DEPOT_PATH=/opt/julia-depot

# Install JSON package into the explicit depot and precompile
RUN julia -e 'using Pkg; Pkg.add("JSON"); using JSON; println("JSON package installed and precompiled")'

COPY circuit.json /app/circuit.json

WORKDIR /app
