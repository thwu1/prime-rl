FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/src

COPY data/profile.pro /app/data/profile.pro
COPY src/StabilityAlgorithms.cc /app/src/StabilityAlgorithms.cc
COPY src/Stability.cc /app/src/Stability.cc
COPY src/Constants.h /app/src/Constants.h
COPY src/DataClasses.cc /app/src/DataClasses.cc
COPY src/DataClasses.h /app/src/DataClasses.h
COPY src/StabilityAlgorithms.h /app/src/StabilityAlgorithms.h

WORKDIR /app
