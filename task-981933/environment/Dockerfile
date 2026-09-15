FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install MiniZinc 2.8.5 bundle (includes Chuffed, Gecode solvers and standard library)
RUN curl -sSfL https://github.com/MiniZinc/MiniZincIDE/releases/download/2.8.5/MiniZincIDE-2.8.5-bundle-linux-x86_64.tgz \
    -o /tmp/mz.tgz && \
    mkdir -p /opt/minizinc && \
    tar xzf /tmp/mz.tgz -C /opt/minizinc --strip-components=1 && \
    rm /tmp/mz.tgz

ENV PATH="/opt/minizinc/bin:$PATH"

COPY instances/ /app/instances/

RUN mkdir -p /app/results /app/models

WORKDIR /app
