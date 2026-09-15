#!/bin/bash

# Deploy optimized classifier
cp /solution/optimized_classifier.py /app/optimized_classifier.py

# Run analysis to produce ruleset_analysis.json
python3 /solution/analyze_ruleset.py

# Verify solution correctness on a sample
python3 -c "
import sys, struct
sys.path.insert(0, '/app')
from optimized_classifier import AdaptiveClassifier
from baseline_classifier import BaselineClassifier

def read_pcap(path, limit=500):
    packets = []
    with open(path, 'rb') as f:
        f.read(24)
        while len(packets) < limit:
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', hdr)
            data = f.read(incl_len)
            if len(data) < 20:
                continue
            ihl = (data[0] & 0x0f) * 4
            proto_num = data[9]
            src_ip = '.'.join(str(b) for b in data[12:16])
            dst_ip = '.'.join(str(b) for b in data[16:20])
            transport = data[ihl:]
            if len(transport) < 4:
                continue
            src_port = struct.unpack('!H', transport[0:2])[0]
            dst_port = struct.unpack('!H', transport[2:4])[0]
            proto_name = 'tcp' if proto_num == 6 else 'udp' if proto_num == 17 else 'other'
            packets.append({'src_ip': src_ip, 'dst_ip': dst_ip, 'src_port': src_port, 'dst_port': dst_port, 'protocol': proto_name})
    return packets

pkts = read_pcap('/app/traffic.pcap', 500)
opt = AdaptiveClassifier('/app/firewall.nft')
base = BaselineClassifier('/app/firewall.nft')

for i, pkt in enumerate(pkts):
    oa, oid = opt.classify(pkt)
    ba, bid = base.classify(pkt)
    assert oa == ba, f'Packet {i}: action mismatch {oa} vs {ba}'
    assert oid == bid, f'Packet {i}: rule_id mismatch {oid} vs {bid}'

unreachable = opt.get_unreachable_rules()
assert len(unreachable) > 0, 'Expected some unreachable rules'
constraints = opt.get_ordering_constraints()
minimal = opt.get_minimal_constraints()
assert len(minimal) < len(constraints), 'Minimal constraints should have fewer entries than full set'

print(f'Solution verified: 500 packets correct, {len(unreachable)} unreachable, {len(constraints)} constraints, {len(minimal)} minimal')
"
