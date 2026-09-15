#!/usr/bin/env python3

"""Parse iperf3 JSON output and write simulator calibration file."""

import json
import sys


def main():
    if len(sys.argv) != 3:
        print("Usage: parse_calibration.py <iperf3_result.json> <calibration_output.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    bits_per_sec = data["end"]["sum_received"]["bits_per_second"]
    measured_gbps = bits_per_sec / 1e9

    # Formula from config.py: RDMA fabric bandwidth = raw TCP / 50, clamped
    remote_bw = measured_gbps * 1000.0 / 50.0
    remote_bw = max(500.0, min(3000.0, remote_bw))

    calibration = {
        "measured_bandwidth_gbps": round(measured_gbps, 2),
        "remote_memory_bandwidth_mb_s": round(remote_bw, 2),
    }

    with open(sys.argv[2], "w") as f:
        json.dump(calibration, f, indent=2)

    print(f"Calibrated: {measured_gbps:.2f} Gbps -> {remote_bw:.2f} MB/s remote BW")


if __name__ == "__main__":
    main()
