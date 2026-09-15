FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip ffmpeg imagemagick && rm -rf /var/lib/apt/lists/*

# Pillow is a task-environment dependency (image I/O for the image-processing task)
RUN pip3 install Pillow==10.4.0 -q

RUN mkdir -p /app
WORKDIR /app

COPY generate_task.py /tmp/generate_task.py
RUN python3 /tmp/generate_task.py && \
    ffmpeg -y -framerate 1 -start_number 0 \
      -i /tmp/frames/frame_%03d.png \
      -c:v ffv1 -pix_fmt gbrp \
      /app/input.mkv && \
    rm -rf /tmp/frames /tmp/generate_task.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 opencv-python-headless==4.10.0.84
