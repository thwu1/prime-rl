FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    git \
    libboost-all-dev \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone the RBG ecosystem (compiler, parser, game examples) and build rbg2cpp
RUN git clone --recurse-submodules https://github.com/marekesz/rbg.git rbg_system && \
    cd rbg_system/rbg2cpp && \
    make rbg2cpp
