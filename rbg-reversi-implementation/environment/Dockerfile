FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    git \
    libboost-all-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone the RBG monorepo
RUN git clone https://github.com/marekesz/rbg.git /app/rbg

# Build the RBG toolchain (parser + compiler)
RUN cd /app/rbg/rbg2cpp && make rbg2cpp

# Copy example game files for reference, then remove the games collection
COPY examples/ /app/examples/
RUN rm -rf /app/rbg/rbgGames /app/rbg/rbgGameSpecificReasoners

WORKDIR /app
