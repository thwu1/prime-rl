FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        build-essential \
        libicu-dev \
        pkg-config \
        curl \
        wget \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/testdata

COPY testdata/GraphemeBreakTest.txt /app/testdata/GraphemeBreakTest.txt
COPY testdata/GraphemeBreakProperty.txt /app/testdata/GraphemeBreakProperty.txt
COPY testdata/WordBreakTest.txt /app/testdata/WordBreakTest.txt
COPY testdata/WordBreakProperty.txt /app/testdata/WordBreakProperty.txt
COPY testdata/SentenceBreakTest.txt /app/testdata/SentenceBreakTest.txt
COPY testdata/SentenceBreakProperty.txt /app/testdata/SentenceBreakProperty.txt
COPY testdata/emoji_data.txt /app/testdata/emoji_data.txt

WORKDIR /app
