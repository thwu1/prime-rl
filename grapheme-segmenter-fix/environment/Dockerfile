FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

RUN curl -fsSL -o /app/data/WordBreakProperty.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/auxiliary/WordBreakProperty.txt" && \
    curl -fsSL -o /app/data/WordBreakTest.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/auxiliary/WordBreakTest.txt" && \
    curl -fsSL -o /app/data/GraphemeBreakProperty.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/auxiliary/GraphemeBreakProperty.txt" && \
    curl -fsSL -o /app/data/GraphemeBreakTest.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/auxiliary/GraphemeBreakTest.txt" && \
    curl -fsSL -o /app/data/SentenceBreakProperty.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/auxiliary/SentenceBreakProperty.txt" && \
    curl -fsSL -o /app/data/SentenceBreakTest.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/auxiliary/SentenceBreakTest.txt" && \
    curl -fsSL -o /app/data/emoji-data.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/emoji/emoji-data.txt" && \
    curl -fsSL -o /app/data/DerivedCoreProperties.txt \
    "https://www.unicode.org/Public/16.0.0/ucd/DerivedCoreProperties.txt"

COPY grapheme_props.py /app/grapheme_props.py
COPY grapheme_segment.py /app/grapheme_segment.py
COPY gen_word_tables.py /app/gen_word_tables.py
COPY word_segment.py /app/word_segment.py
COPY gen_sentence_tables.py /app/gen_sentence_tables.py
COPY sentence_segment.py /app/sentence_segment.py
COPY Makefile /app/Makefile
COPY validate.py /app/validate.py

WORKDIR /app
RUN make all
