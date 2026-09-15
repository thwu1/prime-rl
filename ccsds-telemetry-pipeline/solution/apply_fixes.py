#!/usr/bin/env python3
"""
Apply fixes to the CCSDS TM pipeline Java source files.

Fixes 5 conformance defects:
1. Randomizer: wrong LFSR feedback tap (bit 2 instead of bit 3)
2. CrcCalculator: wrong initial value (0x0000 instead of 0xFFFF)
3. TmFrameDecoder: wrong spacecraft ID bit shift (>>3 instead of >>4)
4. TmFrameDecoder: missing FHP special value handling (0x7FF, 0x7FE)
5. PacketExtractor: no cross-frame packet reassembly

"""


def fix_randomizer():
    """Fix LFSR feedback polynomial: bit 2 -> bit 3."""
    path = '/app/src/Randomizer.java'
    with open(path, 'r') as f:
        code = f.read()
    code = code.replace('(lfsr >> 2)', '(lfsr >> 3)')
    with open(path, 'w') as f:
        f.write(code)
    print("Fixed Randomizer.java: LFSR tap bit 2 -> bit 3")


def fix_crc():
    """Fix CRC initial value: 0x0000 -> 0xFFFF."""
    path = '/app/src/CrcCalculator.java'
    with open(path, 'r') as f:
        code = f.read()
    code = code.replace('int crc = 0x0000', 'int crc = 0xFFFF')
    with open(path, 'w') as f:
        f.write(code)
    print("Fixed CrcCalculator.java: initial value 0x0000 -> 0xFFFF")


def fix_frame_decoder():
    """Fix SCID bit shift and add FHP special value handling."""
    path = '/app/src/TmFrameDecoder.java'
    with open(path, 'r') as f:
        code = f.read()

    # Fix 1: SCID extraction bit shift
    code = code.replace('(word01 >> 3) & 0x3FF', '(word01 >> 4) & 0x3FF')

    # Fix 2: FHP special value handling
    code = code.replace(
        'frame.firstHeaderPointer = fhp;',
        'if (fhp == 0x7FF || fhp == 0x7FE) {\n'
        '            frame.firstHeaderPointer = -1;\n'
        '        } else {\n'
        '            frame.firstHeaderPointer = fhp;\n'
        '        }'
    )

    with open(path, 'w') as f:
        f.write(code)
    print("Fixed TmFrameDecoder.java: SCID shift and FHP handling")


def fix_packet_extractor():
    """Rewrite PacketExtractor with cross-frame packet reassembly support."""
    path = '/app/src/PacketExtractor.java'
    fixed_code = '''import java.util.ArrayList;
import java.util.List;

/**
 * Extracts CCSDS Space Packets from TM frame data fields.
 * Handles packets spanning multiple frame boundaries by buffering
 * partial packet data between consecutive frames.
 */
public class PacketExtractor {
    private byte[] partialBuffer = null;

    /**
     * Extract space packets from the given frame's data field.
     * Call sequentially for consecutive frames to handle spanning packets.
     */
    public List<SpacePacket> extractPackets(TmFrame frame) {
        List<SpacePacket> packets = new ArrayList<>();
        byte[] data = frame.rawData;
        int dataStart = frame.dataStart;
        int dataEnd = frame.dataEnd;
        int fhp = frame.firstHeaderPointer;

        if (fhp == -1) {
            // No new packet starts in this frame - all data is continuation
            appendToPartial(data, dataStart, dataEnd - dataStart);
            tryCompletePacket(packets);
            return packets;
        }

        int newPacketStart = dataStart + fhp;

        // Data before FHP is continuation of previous packet
        if (partialBuffer != null && fhp > 0) {
            appendToPartial(data, dataStart, fhp);
            tryCompletePacket(packets);
        }
        partialBuffer = null;

        // Extract new packets starting from FHP
        int pos = newPacketStart;
        while (pos + 6 <= dataEnd) {
            int word01 = ((data[pos] & 0xFF) << 8) | (data[pos + 1] & 0xFF);
            int version = (word01 >> 13) & 0x7;
            if (version != 0) break;

            int apid = word01 & 0x7FF;
            if (apid == 0x7FF) break;

            int word23 = ((data[pos + 2] & 0xFF) << 8) | (data[pos + 3] & 0xFF);
            int seqFlags = (word23 >> 14) & 0x3;
            int seqCount = word23 & 0x3FFF;

            int pdl = ((data[pos + 4] & 0xFF) << 8) | (data[pos + 5] & 0xFF);
            int packetLength = pdl + 7;

            if (pos + packetLength > dataEnd) {
                // Packet spans to next frame - buffer partial data
                int available = dataEnd - pos;
                partialBuffer = new byte[available];
                System.arraycopy(data, pos, partialBuffer, 0, available);
                break;
            }

            SpacePacket pkt = new SpacePacket();
            pkt.apid = apid;
            pkt.sequenceFlags = seqFlags;
            pkt.sequenceCount = seqCount;
            pkt.dataLength = pdl;
            pkt.userData = new byte[pdl + 1];
            System.arraycopy(data, pos + 6, pkt.userData, 0, pdl + 1);
            packets.add(pkt);
            pos += packetLength;
        }

        return packets;
    }

    private void appendToPartial(byte[] data, int offset, int length) {
        if (length <= 0) return;
        if (partialBuffer == null) {
            partialBuffer = new byte[length];
            System.arraycopy(data, offset, partialBuffer, 0, length);
        } else {
            byte[] newBuf = new byte[partialBuffer.length + length];
            System.arraycopy(partialBuffer, 0, newBuf, 0, partialBuffer.length);
            System.arraycopy(data, offset, newBuf, partialBuffer.length, length);
            partialBuffer = newBuf;
        }
    }

    private void tryCompletePacket(List<SpacePacket> packets) {
        if (partialBuffer == null || partialBuffer.length < 6) return;

        int word01 = ((partialBuffer[0] & 0xFF) << 8) | (partialBuffer[1] & 0xFF);
        int apid = word01 & 0x7FF;
        if (apid == 0x7FF) { partialBuffer = null; return; }

        int word23 = ((partialBuffer[2] & 0xFF) << 8) | (partialBuffer[3] & 0xFF);
        int seqFlags = (word23 >> 14) & 0x3;
        int seqCount = word23 & 0x3FFF;

        int pdl = ((partialBuffer[4] & 0xFF) << 8) | (partialBuffer[5] & 0xFF);
        int packetLength = pdl + 7;

        if (partialBuffer.length >= packetLength) {
            SpacePacket pkt = new SpacePacket();
            pkt.apid = apid;
            pkt.sequenceFlags = seqFlags;
            pkt.sequenceCount = seqCount;
            pkt.dataLength = pdl;
            pkt.userData = new byte[pdl + 1];
            System.arraycopy(partialBuffer, 6, pkt.userData, 0, pdl + 1);
            packets.add(pkt);
            partialBuffer = null;
        }
    }
}
'''
    with open(path, 'w') as f:
        f.write(fixed_code)
    print("Fixed PacketExtractor.java: added cross-frame packet reassembly")


if __name__ == '__main__':
    fix_randomizer()
    fix_crc()
    fix_frame_decoder()
    fix_packet_extractor()
    print("All fixes applied successfully")
