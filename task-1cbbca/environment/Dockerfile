FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include /app/tests

COPY bipartite_buf.hpp /app/include/bipartite_buf.hpp
COPY test_bipartite.cpp /app/tests/test_bipartite.cpp
COPY CMakeLists.txt /app/CMakeLists.txt

RUN test -f /app/include/bipartite_buf.hpp && test -f /app/tests/test_bipartite.cpp && test -f /app/CMakeLists.txt

WORKDIR /app
