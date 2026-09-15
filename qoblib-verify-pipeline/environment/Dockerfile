
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    rustc \
    cargo \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY data/market_split/instance.dat /app/data/market_split/instance.dat
COPY data/market_split/candidate_1.sol /app/data/market_split/candidate_1.sol
COPY data/market_split/candidate_2.sol /app/data/market_split/candidate_2.sol
COPY data/market_split/candidate_3.sol /app/data/market_split/candidate_3.sol
COPY data/market_split/checker/Cargo.toml /app/data/market_split/checker/Cargo.toml
COPY data/market_split/checker/src/bin/check_marketsplit.rs /app/data/market_split/checker/src/bin/check_marketsplit.rs

COPY data/independent_set/instance.col /app/data/independent_set/instance.col
COPY data/independent_set/candidate_1.sol /app/data/independent_set/candidate_1.sol
COPY data/independent_set/candidate_2.sol /app/data/independent_set/candidate_2.sol

COPY data/cvrp/instance.vrp /app/data/cvrp/instance.vrp
COPY data/cvrp/candidate_1.sol /app/data/cvrp/candidate_1.sol
COPY data/cvrp/candidate_2.sol /app/data/cvrp/candidate_2.sol

COPY data/topology/verify/instance.dat /app/data/topology/verify/instance.dat
COPY data/topology/verify/candidate_1.gph /app/data/topology/verify/candidate_1.gph
COPY data/topology/verify/candidate_2.gph /app/data/topology/verify/candidate_2.gph

COPY data/topology/construct/instance.dat /app/data/topology/construct/instance.dat

COPY schema.json /app/schema.json

RUN mkdir -p /app/solutions

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
