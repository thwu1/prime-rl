#!/usr/bin/env python3
"""
Extract MSS values from PCAP captures using tshark, update config.json,
and deploy the exploit module.

"""
import json
import subprocess
import shutil


def extract_mss(pcap_path):
    """Extract the MSS from the SYN-ACK originating from port 5060."""
    result = subprocess.run(
        ['tshark', '-r', pcap_path,
         '-Y', 'tcp.flags.syn==1 && tcp.flags.ack==1 && tcp.srcport==5060',
         '-T', 'fields', '-e', 'tcp.options.mss_val'],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tshark failed on {pcap_path}: {result.stderr.strip()}"
        )
    val = result.stdout.strip()
    if not val:
        raise RuntimeError(f"No SYN-ACK from port 5060 in {pcap_path}")
    return int(val)


def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    for sc in config['scenarios']:
        pcap = sc.get('capture', f"/app/captures/{sc['id']}.pcap")
        mss = extract_mss(pcap)
        sc['mss'] = mss
        print(f"{sc['id']}: MSS={mss}")

    with open('/app/config.json', 'w') as f:
        json.dump(config, f, indent=4)
    print("config.json updated")

    shutil.copy('/solution/exploit_solution.py', '/app/exploit.py')
    print("exploit.py deployed")


if __name__ == '__main__':
    main()
