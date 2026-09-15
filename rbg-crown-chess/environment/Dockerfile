
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    git \
    libboost-all-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone the RBG ecosystem (compiler + parser + games for reference)
WORKDIR /opt
RUN git clone --recurse-submodules --depth 1 https://github.com/marekesz/rbg.git

# Build the rbg2cpp compiler
WORKDIR /opt/rbg/rbg2cpp
RUN make rbg2cpp

# Set up documentation and examples for the agent
COPY docs/ /app/docs/
COPY build_and_perft.sh /app/build_and_perft.sh
RUN chmod +x /app/build_and_perft.sh

# Remove the games directory to prevent trivial copying of solutions
RUN rm -rf /opt/rbg/rbgGames

WORKDIR /app
