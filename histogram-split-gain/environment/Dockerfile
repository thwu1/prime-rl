FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    nlohmann-json3-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY CMakeLists.txt /app/CMakeLists.txt
COPY split_math.hpp /app/split_math.hpp
COPY histogram_scanner.hpp /app/histogram_scanner.hpp
COPY main.cpp /app/main.cpp

WORKDIR /app
