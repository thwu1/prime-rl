#!/usr/bin/env python3
"""Generate reference pcap and raw message files from a correct Speed Daemon implementation."""
import struct
import os

LOCALHOST = b'\x7f\x00\x00\x01'


def write_pcap_global_header(f):
    """Write pcap file global header (little-endian)."""
    f.write(struct.pack("<IHHiIII",
        0xa1b2c3d4,
        2, 4,
        0, 0,
        65535,
        1,  # LINKTYPE_ETHERNET
    ))


def make_eth_ip_tcp(src_port, dst_port, payload, seq, ack):
    """Build Ethernet+IPv4+TCP packet."""
    # Ethernet (14 bytes)
    eth = b'\x02\x00\x00\x00\x00\x01'
    eth += b'\x02\x00\x00\x00\x00\x02'
    eth += struct.pack("!H", 0x0800)

    # TCP (20 bytes)
    data_off_flags = (5 << 12) | 0x018
    tcp = struct.pack("!HHII", src_port, dst_port, seq, ack)
    tcp += struct.pack("!HHHH", data_off_flags, 65535, 0, 0)

    # IPv4 (20 bytes)
    total_len = 20 + 20 + len(payload)
    ip = struct.pack("!BBHHHBBH", 0x45, 0, total_len, 0, 0x4000, 64, 6, 0)
    ip += LOCALHOST + LOCALHOST

    return eth + ip + tcp + payload


def write_packet(f, ts_sec, ts_usec, pkt_data):
    """Write a pcap packet record."""
    f.write(struct.pack("<IIII", ts_sec, ts_usec, len(pkt_data), len(pkt_data)))
    f.write(pkt_data)


# ---- Protocol message constructors (CORRECT implementation) ----

def iam_camera(road, mile, limit):
    return struct.pack("!BHHH", 0x80, road, mile, limit)


def iam_dispatcher(roads):
    msg = struct.pack("!BB", 0x81, len(roads))
    for r in roads:
        msg += struct.pack("!H", r)
    return msg


def plate_msg(p, timestamp):
    raw = p.encode("ascii")
    return struct.pack("!BB", 0x20, len(raw)) + raw + struct.pack("!I", timestamp)


def want_heartbeat(interval):
    return struct.pack("!BI", 0x40, interval)


def ticket_msg(p, road, mile1, ts1, mile2, ts2, speed):
    """Build a CORRECT ticket message (spec field order)."""
    raw = p.encode("ascii")
    buf = struct.pack("!BB", 0x21, len(raw)) + raw
    buf += struct.pack("!HH", road, mile1)
    buf += struct.pack("!I", ts1)
    buf += struct.pack("!H", mile2)
    buf += struct.pack("!I", ts2)
    buf += struct.pack("!H", speed)
    return buf


def error_msg(msg):
    raw = msg.encode("ascii")
    return struct.pack("!BB", 0x10, len(raw)) + raw


class Stream:
    """Track TCP sequence numbers for a connection."""
    def __init__(self, client_port, server_port=9000):
        self.client_port = client_port
        self.server_port = server_port
        self.c_seq = 1000
        self.s_seq = 2000

    def c2s(self, payload):
        pkt = make_eth_ip_tcp(self.client_port, self.server_port,
                              payload, self.c_seq, self.s_seq)
        self.c_seq += len(payload)
        return pkt

    def s2c(self, payload):
        pkt = make_eth_ip_tcp(self.server_port, self.client_port,
                              payload, self.s_seq, self.c_seq)
        self.s_seq += len(payload)
        return pkt


def main():
    os.makedirs("/app/traces/messages", exist_ok=True)

    with open("/app/traces/reference.pcap", "wb") as f:
        write_pcap_global_header(f)
        ts = 1000000

        # === Scenario 1: Forward-direction speed violation ===
        # Road 66, cameras at mile 100 (limit 50) and mile 110
        cam1 = Stream(40001)
        cam2 = Stream(40002)
        disp1 = Stream(40003)

        write_packet(f, ts, 0, cam1.c2s(iam_camera(66, 100, 50)))
        ts += 1
        write_packet(f, ts, 0, cam2.c2s(iam_camera(66, 110, 50)))
        ts += 1
        write_packet(f, ts, 0, disp1.c2s(iam_dispatcher([66])))
        ts += 1
        write_packet(f, ts, 0, cam1.c2s(plate_msg("UN1X", 123456)))
        ts += 1
        write_packet(f, ts, 0, cam2.c2s(plate_msg("UN1X", 123816)))
        ts += 1
        # speed = 10/360*3600 = 100 mph -> speed*100 = 10000
        write_packet(f, ts, 0, disp1.s2c(
            ticket_msg("UN1X", 66, 100, 123456, 110, 123816, 10000)))
        ts += 2

        # === Scenario 2: Reverse-direction (car from mile 20 -> mile 10) ===
        # Road 200, cameras at mile 20 and mile 10, limit 50
        cam3 = Stream(40011)
        cam4 = Stream(40012)
        disp2 = Stream(40013)

        write_packet(f, ts, 0, cam3.c2s(iam_camera(200, 20, 50)))
        ts += 1
        write_packet(f, ts, 0, cam4.c2s(iam_camera(200, 10, 50)))
        ts += 1
        write_packet(f, ts, 0, disp2.c2s(iam_dispatcher([200])))
        ts += 1
        # Car at mile 20 first (ts=0), then mile 10 (ts=100)
        write_packet(f, ts, 0, cam3.c2s(plate_msg("REV1", 0)))
        ts += 1
        write_packet(f, ts, 0, cam4.c2s(plate_msg("REV1", 100)))
        ts += 1
        # CORRECT: mile1=20 (ts=0), mile2=10 (ts=100) — ordered by TIMESTAMP
        # speed = 10/100*3600 = 360 mph -> 36000
        write_packet(f, ts, 0, disp2.s2c(
            ticket_msg("REV1", 200, 20, 0, 10, 100, 36000)))
        ts += 2

        # === Scenario 3: Multi-day ticket spanning ===
        # Road 500, limit 10, cameras at miles 0, 10, 20
        cam5 = Stream(40021)
        cam6 = Stream(40022)
        cam7 = Stream(40023)
        disp3 = Stream(40024)

        write_packet(f, ts, 0, cam5.c2s(iam_camera(500, 0, 10)))
        ts += 1
        write_packet(f, ts, 0, cam6.c2s(iam_camera(500, 10, 10)))
        ts += 1
        write_packet(f, ts, 0, cam7.c2s(iam_camera(500, 20, 10)))
        ts += 1
        write_packet(f, ts, 0, disp3.c2s(iam_dispatcher([500])))
        ts += 1
        # Observation on day 0 (86350 / 86400 = 0)
        write_packet(f, ts, 0, cam5.c2s(plate_msg("SPAN1", 86350)))
        ts += 1
        # Observation on day 1 (86450 / 86400 = 1) -> ticket spans day 0-1
        write_packet(f, ts, 0, cam6.c2s(plate_msg("SPAN1", 86450)))
        ts += 1
        # speed = 10/100*3600 = 360 mph -> 36000
        write_packet(f, ts, 0, disp3.s2c(
            ticket_msg("SPAN1", 500, 0, 86350, 10, 86450, 36000)))
        ts += 1
        # Third observation also on day 1 -> NO second ticket (day 1 blocked)
        write_packet(f, ts, 0, cam7.c2s(plate_msg("SPAN1", 86550)))
        ts += 3
        # No server response packet here — correct behavior is silence

        # === Scenario 4: Heartbeat timing ===
        # WantHeartbeat(10) = 10 deciseconds = 1 second interval
        hb_client = Stream(40031)
        write_packet(f, ts, 0, hb_client.c2s(want_heartbeat(10)))
        # Heartbeats arrive at ~1 second intervals
        for i in range(3):
            ts += 1
            write_packet(f, ts, 0, hb_client.s2c(b'\x41'))
        ts += 2

        # === Scenario 5: Dispatcher sending Plate -> Error ===
        err_client = Stream(40041)
        write_packet(f, ts, 0, err_client.c2s(iam_dispatcher([100])))
        ts += 1
        write_packet(f, ts, 0, err_client.c2s(plate_msg("BAD1", 0)))
        ts += 1
        # Server MUST send error (plate from non-camera)
        write_packet(f, ts, 0, err_client.s2c(error_msg("not a camera")))
        ts += 2

        # === Scenario 6: Ticket buffering (no dispatcher -> connect -> delivery) ===
        # Road 400, limit 60, cameras at mile 0 and mile 10
        cam8 = Stream(40051)
        cam9 = Stream(40052)

        write_packet(f, ts, 0, cam8.c2s(iam_camera(400, 0, 60)))
        ts += 1
        write_packet(f, ts, 0, cam9.c2s(iam_camera(400, 10, 60)))
        ts += 1
        # Observations arrive with NO dispatcher connected for road 400
        write_packet(f, ts, 0, cam8.c2s(plate_msg("BUF1", 0)))
        ts += 1
        write_packet(f, ts, 0, cam9.c2s(plate_msg("BUF1", 100)))
        ts += 2
        # No ticket packet — no dispatcher to send to, must buffer
        # Dispatcher connects and immediately receives the buffered ticket
        disp4 = Stream(40053)
        write_packet(f, ts, 0, disp4.c2s(iam_dispatcher([400])))
        ts += 1
        # speed = 10/100*3600 = 360 mph -> 36000
        write_packet(f, ts, 0, disp4.s2c(
            ticket_msg("BUF1", 400, 0, 0, 10, 100, 36000)))
        ts += 2

        # === Scenario 7: Cross-road same-day deduplication ===
        # Car ticketed on road 800, then speeds on road 801 same day -> suppressed
        cam10 = Stream(40061)
        cam11 = Stream(40062)
        cam12 = Stream(40071)
        cam13 = Stream(40072)
        disp5 = Stream(40073)

        write_packet(f, ts, 0, cam10.c2s(iam_camera(800, 0, 60)))
        ts += 1
        write_packet(f, ts, 0, cam11.c2s(iam_camera(800, 10, 60)))
        ts += 1
        write_packet(f, ts, 0, cam12.c2s(iam_camera(801, 0, 60)))
        ts += 1
        write_packet(f, ts, 0, cam13.c2s(iam_camera(801, 10, 60)))
        ts += 1
        write_packet(f, ts, 0, disp5.c2s(iam_dispatcher([800, 801])))
        ts += 1
        # Car XROAD speeds on road 800 (day 0, ts 0-100)
        write_packet(f, ts, 0, cam10.c2s(plate_msg("XROAD", 0)))
        ts += 1
        write_packet(f, ts, 0, cam11.c2s(plate_msg("XROAD", 100)))
        ts += 1
        # Ticket for road 800 issued (360 mph -> 36000)
        write_packet(f, ts, 0, disp5.s2c(
            ticket_msg("XROAD", 800, 0, 0, 10, 100, 36000)))
        ts += 1
        # Same car XROAD speeds on road 801 (still day 0, ts 200-300)
        write_packet(f, ts, 0, cam12.c2s(plate_msg("XROAD", 200)))
        ts += 1
        write_packet(f, ts, 0, cam13.c2s(plate_msg("XROAD", 300)))
        ts += 2
        # NO ticket for road 801 — day 0 already covered by cross-road dedup
        # (absence of server response is the correct behavior)

        # === Scenario 8: Dispatcher disconnect and reconnect ===
        # Road 700, dispatcher connects, disconnects, violation occurs,
        # new dispatcher connects and receives buffered ticket
        cam14 = Stream(40081)
        cam15 = Stream(40082)
        disp6 = Stream(40083)

        write_packet(f, ts, 0, cam14.c2s(iam_camera(700, 0, 60)))
        ts += 1
        write_packet(f, ts, 0, cam15.c2s(iam_camera(700, 10, 60)))
        ts += 1
        # First dispatcher connects then disconnects (FIN)
        write_packet(f, ts, 0, disp6.c2s(iam_dispatcher([700])))
        ts += 2
        # (dispatcher disconnected — represented by session ending)
        # Observations arrive while no dispatcher is active
        write_packet(f, ts, 0, cam14.c2s(plate_msg("CLEN", 0)))
        ts += 1
        write_packet(f, ts, 0, cam15.c2s(plate_msg("CLEN", 100)))
        ts += 2
        # No ticket packet — stale dispatcher must have been removed
        # New dispatcher connects and receives buffered ticket
        disp7 = Stream(40084)
        write_packet(f, ts, 0, disp7.c2s(iam_dispatcher([700])))
        ts += 1
        # speed = 10/100*3600 = 360 mph -> 36000
        write_packet(f, ts, 0, disp7.s2c(
            ticket_msg("CLEN", 700, 0, 0, 10, 100, 36000)))
        ts += 1

        # === Scenario 9: Speed threshold boundary ===
        # Car at exactly the speed limit -> no ticket
        # Car at 0.5 mph over -> ticket
        cam16 = Stream(40091)
        cam17 = Stream(40092)
        disp8 = Stream(40093)

        write_packet(f, ts, 0, cam16.c2s(iam_camera(300, 0, 60)))
        ts += 1
        write_packet(f, ts, 0, cam17.c2s(iam_camera(300, 60, 60)))
        ts += 1
        write_packet(f, ts, 0, disp8.c2s(iam_dispatcher([300])))
        ts += 1
        # 60 miles / 3600 seconds = exactly 60 mph = limit -> NO ticket
        write_packet(f, ts, 0, cam16.c2s(plate_msg("EXACT", 0)))
        ts += 1
        write_packet(f, ts, 0, cam17.c2s(plate_msg("EXACT", 3600)))
        ts += 2
        # No ticket packet — car at exactly the limit

        cam18 = Stream(40101)
        cam19 = Stream(40102)
        disp9 = Stream(40103)

        write_packet(f, ts, 0, cam18.c2s(iam_camera(301, 0, 100)))
        ts += 1
        write_packet(f, ts, 0, cam19.c2s(iam_camera(301, 201, 100)))
        ts += 1
        write_packet(f, ts, 0, disp9.c2s(iam_dispatcher([301])))
        ts += 1
        # 201 miles / 7200 seconds = 100.5 mph = limit + 0.5 -> ticket
        write_packet(f, ts, 0, cam18.c2s(plate_msg("HALF", 0)))
        ts += 1
        write_packet(f, ts, 0, cam19.c2s(plate_msg("HALF", 7200)))
        ts += 1
        # speed = 100.5 * 100 = 10050
        write_packet(f, ts, 0, disp9.s2c(
            ticket_msg("HALF", 301, 0, 0, 201, 7200, 10050)))
        ts += 1

    # --- Individual message files for socat/nc testing ---

    with open("/app/traces/messages/want_heartbeat_10.bin", "wb") as mf:
        mf.write(want_heartbeat(10))

    with open("/app/traces/messages/dispatcher_then_plate.bin", "wb") as mf:
        mf.write(iam_dispatcher([100]) + plate_msg("BAD1", 0))

    with open("/app/traces/messages/camera_and_plate.bin", "wb") as mf:
        mf.write(iam_camera(123, 8, 60) + plate_msg("TEST", 0))

    # Reference ticket bytes for comparison against skeleton's _build_ticket_bytes
    with open("/app/traces/messages/reference_ticket_un1x.bin", "wb") as mf:
        mf.write(ticket_msg("UN1X", 66, 100, 123456, 110, 123816, 10000))

    with open("/app/traces/messages/reference_ticket_rev1.bin", "wb") as mf:
        mf.write(ticket_msg("REV1", 200, 20, 0, 10, 100, 36000))

    # --- README ---
    with open("/app/traces/README.txt", "w") as mf:
        mf.write(
            "Reference data from a verified conformant Speed Daemon implementation.\n"
            "\n"
            "reference.pcap\n"
            "  Packet capture of multiple independent TCP sessions showing\n"
            "  correct server behavior. Server port is 9000. Each session\n"
            "  uses a distinct client port range. Scenarios covered:\n"
            "    1. Forward-direction speed violation (ports 40001-40003)\n"
            "    2. Reverse-direction ticket ordering (ports 40011-40013)\n"
            "    3. Multi-day ticket spanning with dedup (ports 40021-40024)\n"
            "    4. Heartbeat timing at 10 deciseconds (port 40031)\n"
            "    5. Dispatcher sending Plate -> Error (port 40041)\n"
            "    6. Ticket buffering until dispatcher connects (ports 40051-40053)\n"
            "    7. Cross-road same-day deduplication (ports 40061-40073)\n"
            "    8. Dispatcher disconnect/reconnect with buffering (ports 40081-40084)\n"
            "    9. Speed threshold boundary cases (ports 40091-40103)\n"
            "\n"
            "messages/\n"
            "  Individual protocol messages as raw binary for testing.\n"
            "  - want_heartbeat_10.bin         WantHeartbeat(interval=10)\n"
            "  - dispatcher_then_plate.bin     IAmDispatcher + Plate on one stream\n"
            "  - camera_and_plate.bin          IAmCamera + Plate on one stream\n"
            "  - reference_ticket_un1x.bin     Correct ticket encoding for UN1X\n"
            "  - reference_ticket_rev1.bin     Correct ticket encoding for REV1\n"
            "\n"
            "Useful commands:\n"
            "  tshark -r /app/traces/reference.pcap -x\n"
            "  tshark -r /app/traces/reference.pcap -Y 'tcp.srcport==9000' -x\n"
            "  xxd /app/traces/messages/reference_ticket_un1x.bin\n"
            "  cat messages/camera_and_plate.bin | socat -t5 - TCP:localhost:9000 | xxd\n"
        )


if __name__ == "__main__":
    main()
