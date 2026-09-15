import java.util.ArrayList;
import java.util.List;

/**
 * Extracts CCSDS Space Packets from TM frame data fields.
 * Uses the First Header Pointer to locate packet boundaries.
 */
public class PacketExtractor {

    /**
     * Extract all complete space packets from the given frame's data field.
     */
    public List<SpacePacket> extractPackets(TmFrame frame) {
        List<SpacePacket> packets = new ArrayList<>();
        byte[] data = frame.rawData;
        int dataStart = frame.dataStart;
        int dataEnd = frame.dataEnd;
        int fhp = frame.firstHeaderPointer;

        // Start extracting packets from the First Header Pointer position
        int pos = dataStart + fhp;

        while (pos + 6 <= dataEnd) {
            // Read Space Packet primary header (6 bytes)
            int word01 = ((data[pos] & 0xFF) << 8) | (data[pos + 1] & 0xFF);
            int version = (word01 >> 13) & 0x7;
            if (version != 0) break; // not a CCSDS space packet

            int apid = word01 & 0x7FF;
            if (apid == 0x7FF) break; // idle packet marker

            int word23 = ((data[pos + 2] & 0xFF) << 8) | (data[pos + 3] & 0xFF);
            int seqFlags = (word23 >> 14) & 0x3;
            int seqCount = word23 & 0x3FFF;

            int pdl = ((data[pos + 4] & 0xFF) << 8) | (data[pos + 5] & 0xFF);
            int packetLength = pdl + 7;

            // Check if the complete packet fits within this frame
            if (pos + packetLength > dataEnd) {
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
}
