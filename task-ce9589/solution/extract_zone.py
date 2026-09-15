#!/usr/bin/env python3
"""Extract DNS zone data from a pcap file and write a BIND zone file.

Parses pcap directly (Ethernet/IP/UDP/DNS) to extract authoritative
DNS response records for a target domain, filtering noise traffic.
"""

import struct
import socket
import ipaddress
import sys


def decode_name(data, offset):
    parts = []
    end = None
    jumps = 0
    pos = offset
    while pos < len(data):
        l = data[pos]
        if l == 0:
            pos += 1
            break
        if (l & 0xC0) == 0xC0:
            if jumps > 10:
                break
            if end is None:
                end = pos + 2
            ptr = ((l & 0x3F) << 8) | data[pos + 1]
            pos = ptr
            jumps += 1
        else:
            pos += 1
            parts.append(data[pos:pos + l].decode('ascii'))
            pos += l
    if end is None:
        end = pos
    return '.'.join(parts) + '.' if parts else '.', end


def extract_records(pcap_path, domain):
    domain_lower = domain.lower().rstrip('.')
    records = []
    soa = None

    with open(pcap_path, 'rb') as f:
        f.read(24)  # skip global header
        while True:
            pkt_hdr = f.read(16)
            if len(pkt_hdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', pkt_hdr)
            pkt = f.read(incl_len)

            if len(pkt) < 42:
                continue
            dns = pkt[42:]  # skip Ethernet(14) + IP(20) + UDP(8)
            if len(dns) < 12:
                continue

            qid, flags, qdcount, ancount, nscount, arcount = \
                struct.unpack('!HHHHHH', dns[:12])

            qr = (flags >> 15) & 1
            rcode = flags & 0xF
            if qr != 1 or rcode != 0:
                continue

            offset = 12
            if qdcount < 1:
                continue
            qname, offset = decode_name(dns, offset)
            if offset + 4 > len(dns):
                continue
            qtype = struct.unpack('!H', dns[offset:offset + 2])[0]
            offset += 4

            qn = qname.lower().rstrip('.')
            if qn != domain_lower and not qn.endswith('.' + domain_lower):
                continue

            for _ in range(ancount):
                if offset >= len(dns):
                    break
                rname, offset = decode_name(dns, offset)
                if offset + 10 > len(dns):
                    break
                rtype, rclass, ttl, rdlen = struct.unpack('!HHIH', dns[offset:offset + 10])
                offset += 10
                rd_start = offset

                rn = rname.lower().rstrip('.')

                if rtype == 1 and rdlen == 4:
                    ip = '.'.join(str(b) for b in dns[offset:offset + 4])
                    records.append((rn, 'A', ttl, ip))
                elif rtype == 28 and rdlen == 16:
                    ip = str(ipaddress.IPv6Address(dns[offset:offset + 16]))
                    records.append((rn, 'AAAA', ttl, ip))
                elif rtype == 5:
                    target, _ = decode_name(dns, offset)
                    records.append((rn, 'CNAME', ttl, target))
                elif rtype == 2:
                    ns, _ = decode_name(dns, offset)
                    records.append((rn, 'NS', ttl, ns))
                elif rtype == 15:
                    pref = struct.unpack('!H', dns[offset:offset + 2])[0]
                    exchange, _ = decode_name(dns, offset + 2)
                    records.append((rn, 'MX', ttl, f'{pref} {exchange}'))
                elif rtype == 16:
                    txts = []
                    pos = offset
                    while pos < offset + rdlen:
                        tl = dns[pos]
                        pos += 1
                        txts.append(dns[pos:pos + tl].decode('ascii', errors='replace'))
                        pos += tl
                    records.append((rn, 'TXT', ttl, ''.join(txts)))
                elif rtype == 6:
                    mname, p = decode_name(dns, offset)
                    rname_soa, p = decode_name(dns, p)
                    serial, refresh, retry, expire, minimum = \
                        struct.unpack('!IIIII', dns[p:p + 20])
                    soa = (mname, rname_soa, serial, refresh, retry, expire, minimum, ttl)

                offset = rd_start + rdlen

    return soa, records


def write_zone(path, domain, soa, records):
    dc = domain.rstrip('.')
    with open(path, 'w') as f:
        f.write(f'$ORIGIN {dc}.\n')
        f.write('$TTL 3600\n')

        if soa:
            mname, rname, serial, refresh, retry, expire, minimum, ttl = soa
            f.write(f'@       IN  SOA     {mname} {rname} (\n')
            f.write(f'                        {serial}  ; serial\n')
            f.write(f'                        {refresh}        ; refresh\n')
            f.write(f'                        {retry}         ; retry\n')
            f.write(f'                        {expire}      ; expire\n')
            f.write(f'                        {minimum}       ; minimum\n')
            f.write(f'                    )\n')

        seen = set()
        for rn, rtype, ttl, rdata in records:
            key = (rn, rtype, rdata)
            if key in seen:
                continue
            seen.add(key)

            if rn == dc:
                dname = '@'
            elif rn.endswith('.' + dc):
                dname = rn[:-(len(dc) + 1)]
            else:
                dname = rn + '.'

            if rtype in ('CNAME', 'NS'):
                if not rdata.endswith('.'):
                    rdata += '.'
            elif rtype == 'MX':
                parts = rdata.split(' ', 1)
                if len(parts) == 2 and not parts[1].endswith('.'):
                    rdata = parts[0] + ' ' + parts[1] + '.'
            elif rtype == 'TXT':
                rdata = f'"{rdata}"'

            f.write(f'{dname:12s}IN  {rtype:8s}{rdata}\n')


if __name__ == '__main__':
    pcap = sys.argv[1] if len(sys.argv) > 1 else '/app/captures/dns_traffic.pcap'
    out = sys.argv[2] if len(sys.argv) > 2 else '/app/zones/services.lab.zone'
    domain = sys.argv[3] if len(sys.argv) > 3 else 'services.lab'

    soa, records = extract_records(pcap, domain)
    write_zone(out, domain, soa, records)
    print(f'Generated {out} with SOA + {len(records)} records for {domain}')
