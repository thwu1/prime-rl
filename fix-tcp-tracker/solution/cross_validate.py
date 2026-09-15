#!/usr/bin/env python3
"""Cross-validate TCP tracker output against tshark-derived byte counts.

Uses TCP ACK-based sequence number accounting to compute exact unique
payload bytes per direction. With tshark's default relative sequence
numbers, each cleanly-closed connection has:

    unique_bytes = max_peer_ack - 2

where -2 accounts for SYN and FIN each consuming one sequence number.

This is more reliable than summing tcp.len with a retransmission exclusion
filter (not tcp.analysis.retransmission), which misclassifies gap-filling
segments in reordered traffic as retransmissions.

"""
import json
import os
import subprocess


def get_client_endpoint(pcap_path):
    """Find the client (SYN initiator) IP and port using tshark."""
    result = subprocess.run(
        ["tshark", "-r", pcap_path, "-T", "fields",
         "-e", "ip.src", "-e", "tcp.srcport",
         "-Y", "tcp.flags.syn == 1 and tcp.flags.ack == 0",
         "-c", "1"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"tshark failed on {pcap_path}: {result.stderr}")
    parts = result.stdout.strip().split("\t")
    return parts[0], int(parts[1])


def get_unique_bytes(pcap_path, client_ip, client_port):
    """Compute unique payload bytes per direction using ACK-based accounting.

    With tshark's default relative sequence numbers, the final ACK from
    each peer equals (unique_data_bytes + 2), where +2 accounts for
    SYN and FIN each consuming one sequence number.

    This correctly handles retransmissions, out-of-order segments, and
    sequence number wrapping (tshark's relative mode handles wrapping
    internally).
    """
    # Server->Client ACKs (acknowledge client data)
    r = subprocess.run(
        ["tshark", "-r", pcap_path, "-T", "fields",
         "-e", "tcp.ack",
         "-Y", f"ip.dst == {client_ip} and tcp.dstport == {client_port} "
               f"and tcp.flags.ack == 1"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"tshark failed on {pcap_path}: {r.stderr}")
    server_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

    # Client->Server ACKs (acknowledge server data)
    r = subprocess.run(
        ["tshark", "-r", pcap_path, "-T", "fields",
         "-e", "tcp.ack",
         "-Y", f"ip.src == {client_ip} and tcp.srcport == {client_port} "
               f"and tcp.flags.ack == 1"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"tshark failed on {pcap_path}: {r.stderr}")
    client_acks = [int(x) for x in r.stdout.strip().split("\n") if x.strip()]

    # unique_bytes = max_peer_ack - 2 (SYN + FIN each consume 1 seq num)
    client_bytes = max(server_acks) - 2 if server_acks else 0
    server_bytes = max(client_acks) - 2 if client_acks else 0

    return client_bytes, server_bytes


def main():
    trace_path = "/app/trace.json"
    captures_dir = "/app/captures"
    output_path = "/app/cross_validation.json"

    with open(trace_path) as f:
        trace = json.load(f)

    captures = []
    for conn in trace["connections"]:
        pcap_path = os.path.join(captures_dir, conn["file"])
        if not os.path.exists(pcap_path):
            print(f"WARNING: {pcap_path} not found, skipping")
            continue

        client_ip, client_port = get_client_endpoint(pcap_path)
        tshark_cb, tshark_sb = get_unique_bytes(pcap_path, client_ip, client_port)

        entry = {
            "file": conn["file"],
            "tracker_client_bytes": conn["client_bytes"],
            "tracker_server_bytes": conn["server_bytes"],
            "tshark_client_bytes": tshark_cb,
            "tshark_server_bytes": tshark_sb,
            "match": (conn["client_bytes"] == tshark_cb and
                      conn["server_bytes"] == tshark_sb),
        }
        captures.append(entry)

        status = "OK" if entry["match"] else "MISMATCH"
        print(f"  {conn['file']}: {status} "
              f"(tracker: {conn['client_bytes']}/{conn['server_bytes']}, "
              f"tshark: {tshark_cb}/{tshark_sb})")

    output = {"captures": captures}
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    matched = sum(1 for c in captures if c["match"])
    print(f"\nCross-validation: {matched}/{len(captures)} captures match")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
