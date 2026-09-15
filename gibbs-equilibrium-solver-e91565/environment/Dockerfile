FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        g++ make cmake python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY thermo.hpp /app/thermo.hpp
COPY activity.hpp /app/activity.hpp
COPY activity.cpp /app/activity.cpp
COPY solver.hpp /app/solver.hpp
COPY solver.cpp /app/solver.cpp
COPY main.cpp /app/main.cpp
COPY CMakeLists.txt /app/CMakeLists.txt
COPY problem_1.txt /app/problem_1.txt
COPY problem_2.txt /app/problem_2.txt
COPY problem_3.txt /app/problem_3.txt
COPY problem_4.txt /app/problem_4.txt
COPY problem_5.txt /app/problem_5.txt

