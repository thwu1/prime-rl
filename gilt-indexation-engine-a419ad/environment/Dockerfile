FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    nlohmann-json3-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY main.cpp /app/main.cpp
COPY date_utils.h /app/date_utils.h
COPY rpi.h /app/rpi.h
COPY rpi.cpp /app/rpi.cpp
COPY schedule.h /app/schedule.h
COPY schedule.cpp /app/schedule.cpp
COPY pricing.h /app/pricing.h
COPY pricing.cpp /app/pricing.cpp
COPY analytics.h /app/analytics.h
COPY analytics.cpp /app/analytics.cpp
COPY Makefile /app/Makefile
COPY rpi_data.csv /app/rpi_data.csv
COPY gilts.json /app/gilts.json

WORKDIR /app
