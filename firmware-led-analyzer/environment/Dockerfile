FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/firmware/c /app/firmware/rust

COPY firmware/c/ubt_led.h /app/firmware/c/ubt_led.h
COPY firmware/c/ubt_led.c /app/firmware/c/ubt_led.c
COPY firmware/c/ws_commands.h /app/firmware/c/ws_commands.h
COPY firmware/c/ws_commands.c /app/firmware/c/ws_commands.c
COPY firmware/rust/led_cmd.rs /app/firmware/rust/led_cmd.rs
COPY firmware/rust/led_driver.rs /app/firmware/rust/led_driver.rs
COPY firmware/rust/error.rs /app/firmware/rust/error.rs
COPY reference.py /app/reference.py

WORKDIR /app
