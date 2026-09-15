FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip curl make diffutils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/segmenter /app/scripts

RUN curl -fsSL -o /app/data/GraphemeBreakProperty.txt \
        https://www.unicode.org/Public/17.0.0/ucd/auxiliary/GraphemeBreakProperty.txt && \
    curl -fsSL -o /app/data/GraphemeBreakTest.txt \
        https://www.unicode.org/Public/17.0.0/ucd/auxiliary/GraphemeBreakTest.txt

COPY app/ /app/

WORKDIR /app
