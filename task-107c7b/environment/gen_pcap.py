#!/usr/bin/env python3
"""Generate /app/bgp_capture.pcap from RFC 9235 raw IP packet hex dumps."""
import struct

PCAP_MAGIC = 0xa1b2c3d4
PCAP_VERSION_MAJOR = 2
PCAP_VERSION_MINOR = 4
PCAP_SNAPLEN = 65535
PCAP_LINKTYPE_RAW = 101

# Client SYN packets from each RFC 9235 test connection
PACKETS = [
    # 4.1: IPv4 HMAC-SHA-1-96 covers options
    "45e0004cdd0f4000ff06bf6b0a0b0c0dac1b1c1d"
    "e9d700b3fbfbab5a00000000e002ffffcac40000"
    "020405b4010303080402080a00155ab700000000"
    "1d103d542ee437c6f8ede6d7c4d602e7",
    # 4.2: IPv4 HMAC-SHA-1-96 omits options
    "45e0004c53994000ff0648e20a0b0c0dac1b1c1d"
    "ff1200b3cb0efbee00000000e002ffff541f0000"
    "020405b4010303080402080a00024cce00000000"
    "1d103d5480af3cfeb85368937b8f9ec2",
    # 5.1: IPv4 AES-128-CMAC-96 covers options
    "45e0004c7b9f4000ff0620dc0a0b0c0dac1b1c1d"
    "c4fa00b3787a1ddf00000000e002ffff5a0f0000"
    "020405b4010303080402080a00017ed000000000"
    "1d103d54e477e99c8040765498e55091",
    # 5.2: IPv4 AES-128-CMAC-96 omits options
    "45e0004cf22e4000ff06aa4c0a0b0c0dac1b1c1d"
    "da1c00b3389bed7100000000e002ffff70bf0000"
    "020405b4010303080402080a000185e100000000"
    "1d103d54c44e60cb31f7c0b1de3d2749",
    # 6.1: IPv6 HMAC-SHA-1-96 covers options
    "6e0891dc00380640"
    "fd000000000000000000000000000001"
    "fd000000000000000000000000000002"
    "f7e400b3176a833f00000000e002ffff47210000"
    "020405a0010303080402080a0041d08700000000"
    "1d103d549033ec3d7334b64c5edd039f",
    # 6.2: IPv6 HMAC-SHA-1-96 omits options
    "6e078fcd00380640"
    "fd000000000000000000000000000001"
    "fd000000000000000000000000000002"
    "c6cd00b3020c1e6900000000e002ffffa41a0000"
    "020405a0010303080402080a009db95b00000000"
    "1d103d54885698b0530ed4d5a15f8346",
    # 7.1: IPv6 AES-128-CMAC-96 covers options
    "6e04a70600380640"
    "fd000000000000000000000000000001"
    "fd000000000000000000000000000002"
    "f85a00b3193cccec00000000e002ffffde5d0000"
    "020405a0010303080402080a13e4ab9900000000"
    "1d103d5459b588107481ac6dc3927040",
    # 7.2: IPv6 AES-128-CMAC-96 omits options
    "6e093d7600380640"
    "fd000000000000000000000000000001"
    "fd000000000000000000000000000002"
    "f28800b3b01da74a00000000e002ffff75ff0000"
    "020405a0010303080402080a14275b3b00000000"
    "1d103d543d45b4342de8bb1530847898",
]


def write_pcap(filename, packets):
    with open(filename, 'wb') as f:
        f.write(struct.pack('<IHHiIII',
                            PCAP_MAGIC, PCAP_VERSION_MAJOR, PCAP_VERSION_MINOR,
                            0, 0, PCAP_SNAPLEN, PCAP_LINKTYPE_RAW))
        for idx, pkt_hex in enumerate(packets):
            pkt_data = bytes.fromhex(pkt_hex.replace(' ', '').replace('\n', ''))
            pkt_len = len(pkt_data)
            f.write(struct.pack('<IIII', 1000000 + idx, 0, pkt_len, pkt_len))
            f.write(pkt_data)


write_pcap('/app/bgp_capture.pcap', PACKETS)
print(f"Generated /app/bgp_capture.pcap with {len(PACKETS)} packets")
