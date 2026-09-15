FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    espeak-ng \
    ffmpeg \
    libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 soundfile==0.12.1 pyyaml==6.0.2

RUN mkdir -p /app/stt_verifier

COPY stt_verifier/__init__.py /app/stt_verifier/__init__.py
COPY stt_verifier/wer.py /app/stt_verifier/wer.py
COPY stt_verifier/vad.py /app/stt_verifier/vad.py
COPY stt_verifier/matcher.py /app/stt_verifier/matcher.py
COPY stt_verifier/synthesize.py /app/stt_verifier/synthesize.py
COPY stt_verifier/transcribe.py /app/stt_verifier/transcribe.py
COPY stt_verifier/junit.py /app/stt_verifier/junit.py
COPY stt_verifier/pipeline.py /app/stt_verifier/pipeline.py
COPY test_spec.yaml /app/test_spec.yaml

WORKDIR /app
