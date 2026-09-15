FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ make git wget python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone Stockfish source repository
RUN git clone --depth 1 https://github.com/official-stockfish/Stockfish.git /app/Stockfish

WORKDIR /app/Stockfish/src

# Download the default NNUE network file (name extracted from evaluate.h)
RUN NNUE_FILE=$(sed -n 's/.*EvalFileDefaultName "\([^"]*\)".*/\1/p' /app/Stockfish/src/evaluate.h) && \
    echo "Downloading NNUE network: ${NNUE_FILE}" && \
    wget -q "https://tests.stockfishchess.org/api/nn/${NNUE_FILE}" -O "${NNUE_FILE}" && \
    echo "${NNUE_FILE}" > /app/nnue_filename.txt

# Build Stockfish binary (basic x86-64 without SIMD extensions)
RUN make -j build ARCH=x86-64

# Copy binary and network file to /app for easy access
RUN NNUE_FILE=$(cat /app/nnue_filename.txt) && \
    cp stockfish /app/stockfish && \
    cp "${NNUE_FILE}" "/app/${NNUE_FILE}"

WORKDIR /app
