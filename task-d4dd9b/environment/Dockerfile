FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Build and install the DataFlow v2 library (headers + static lib only, no CMake integration)
COPY dataflow/ /tmp/dataflow_build/
RUN cd /tmp/dataflow_build && \
    g++ -std=c++17 -c -Iinclude src/core.cpp -o core.o && \
    g++ -std=c++17 -c -Iinclude src/pipeline.cpp -o pipeline.o && \
    g++ -std=c++17 -c -Iinclude src/codec.cpp -o codec.o && \
    ar rcs libdataflow.a core.o pipeline.o codec.o && \
    cp libdataflow.a /usr/local/lib/ && \
    mkdir -p /usr/local/include && \
    cp -r include/dataflow /usr/local/include/ && \
    ldconfig && \
    rm -rf /tmp/dataflow_build

# Create empty CMake config directory (config files were never generated after manual install)
RUN mkdir -p /usr/local/lib/cmake/DataFlow

# Set up the project with build issues
COPY app/ /app/

WORKDIR /app
