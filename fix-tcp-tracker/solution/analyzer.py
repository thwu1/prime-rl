#!/usr/bin/env python3
"""
TCP Connection Quality Auditor — analyzes pcap files using tshark.

"""

import subprocess
import json
import os
import sys


def tshark(pcap, extra_args):
    """Run tshark on a pcap file with extra arguments, return stdout."""
    cmd = ["tshark", "-r", pcap, "-n"] + extra_args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def get_stream_ids(pcap):
    """Return sorted list of unique tcp.stream indices in a pcap."""
    out = tshark(pcap, ["-T", "fields", "-e", "tcp.stream"])
    if not out:
        return []
    return sorted(set(int(x) for x in out.split("\n") if x.strip()))


def count_matching(pcap, display_filter):
    """Count packets matching a display filter."""
    out = tshark(pcap, ["-Y", display_filter, "-T", "fields", "-e", "frame.number"])
    if not out:
        return 0
    return len([x for x in out.split("\n") if x.strip()])


def get_stream_endpoints(pcap, sid):
    """Get (src_ip:port, dst_ip:port) for the first packet in a stream."""
    out = tshark(pcap, [
        "-Y", f"tcp.stream=={sid}",
        "-T", "fields",
        "-e", "ip.src", "-e", "tcp.srcport",
        "-e", "ip.dst", "-e", "tcp.dstport",
        "-c", "1",
    ])
    parts = out.strip().split("\t")
    if len(parts) >= 4:
        return f"{parts[0]}:{parts[1]}", f"{parts[2]}:{parts[3]}"
    return "unknown", "unknown"


def get_data_bytes(pcap, sid):
    """Sum tcp.len for non-retransmission packets in a stream."""
    out = tshark(pcap, [
        "-Y", f"tcp.stream=={sid} && !tcp.analysis.retransmission && tcp.len>0",
        "-T", "fields", "-e", "tcp.len",
    ])
    if not out:
        return 0
    return sum(int(x) for x in out.split("\n") if x.strip())


def get_duration(pcap, sid):
    """Get stream duration from first to last packet timestamp."""
    out = tshark(pcap, [
        "-Y", f"tcp.stream=={sid}",
        "-T", "fields", "-e", "frame.time_relative",
    ])
    if not out:
        return 0.0
    times = [float(x) for x in out.split("\n") if x.strip()]
    if len(times) < 2:
        return 0.0
    return round(max(times) - min(times), 6)


def has_fin_both_sides(pcap, sid):
    """Check whether both endpoints sent FIN."""
    out = tshark(pcap, [
        "-Y", f"tcp.stream=={sid} && tcp.flags.fin==1",
        "-T", "fields", "-e", "ip.src",
    ])
    if not out:
        return False
    ips = set(x.strip() for x in out.split("\n") if x.strip())
    return len(ips) >= 2


def classify(metrics):
    """Classify a session based on extracted metrics."""
    if metrics["has_rst"]:
        return "rst_abort"
    if metrics["has_zero_window"]:
        return "zero_window"
    if metrics["retransmission_rate"] > 0.15:
        return "retransmission_storm"
    return "healthy"


def compute_score(classification, metrics):
    """Assign a quality score (0-100) based on classification and metrics."""
    if classification == "healthy":
        base = 90.0
        penalty = metrics["retransmission_rate"] * 50.0
        return round(max(80.0, base - penalty), 2)
    elif classification == "zero_window":
        return 40.0
    elif classification == "retransmission_storm":
        return 20.0
    elif classification == "rst_abort":
        return 10.0
    return 50.0


def analyze_pcap(pcap_path):
    """Analyze all TCP streams in a single pcap file."""
    fname = os.path.basename(pcap_path)
    sessions = []

    for sid in get_stream_ids(pcap_path):
        src, dst = get_stream_endpoints(pcap_path, sid)

        total_pkts = count_matching(pcap_path, f"tcp.stream=={sid}")
        retrans = count_matching(pcap_path, f"tcp.stream=={sid} && tcp.analysis.retransmission")
        rst = count_matching(pcap_path, f"tcp.stream=={sid} && tcp.flags.reset==1") > 0
        zw = count_matching(pcap_path, f"tcp.stream=={sid} && tcp.analysis.zero_window") > 0
        fin_close = has_fin_both_sides(pcap_path, sid)
        data_bytes = get_data_bytes(pcap_path, sid)
        dur = get_duration(pcap_path, sid)

        rate = retrans / total_pkts if total_pkts > 0 else 0.0

        metrics = {
            "total_packets": total_pkts,
            "retransmission_count": retrans,
            "retransmission_rate": round(rate, 4),
            "bytes_transferred": data_bytes,
            "duration_sec": round(dur, 4),
            "has_rst": rst,
            "has_zero_window": zw,
            "orderly_close": fin_close and not rst,
        }

        cls = classify(metrics)
        score = compute_score(cls, metrics)

        sessions.append({
            "file": fname,
            "stream_index": sid,
            "src": src,
            "dst": dst,
            "classification": cls,
            "quality_score": score,
            "metrics": metrics,
        })

    return sessions


def main():
    capture_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/captures"

    all_sessions = []
    for fname in sorted(os.listdir(capture_dir)):
        if fname.endswith(".pcap"):
            path = os.path.join(capture_dir, fname)
            all_sessions.extend(analyze_pcap(path))

    # Rank by quality score descending, ties broken by filename then stream_index
    all_sessions.sort(key=lambda s: (-s["quality_score"], s["file"], s["stream_index"]))
    ranking = [f"{s['file']}:{s['stream_index']}" for s in all_sessions]

    report = {"sessions": all_sessions, "ranking": ranking}

    out_path = "/app/report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {out_path} ({len(all_sessions)} sessions)")


if __name__ == "__main__":
    main()
