FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include /app/tests

COPY bytecode.hpp /app/include/
COPY vm.hpp /app/include/
COPY compiler.hpp /app/include/
COPY test_arithmetic.cpp test_variables.cpp test_functions.cpp /app/tests/
COPY test_power.cpp test_comparisons.cpp test_ternary.cpp /app/tests/
COPY test_letbind.cpp test_constfold.cpp test_complex.cpp /app/tests/
COPY Makefile /app/

WORKDIR /app
