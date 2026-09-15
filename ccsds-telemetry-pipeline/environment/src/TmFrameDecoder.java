/**
 * Decodes CCSDS TM Transfer Frames per CCSDS 132.0-B-2.
 * Parses the 6-byte primary header, optional OCF, and CRC-16.
 */
public class TmFrameDecoder {
    private final int frameLength;
    private final boolean hasCrc;

    public TmFrameDecoder(int frameLength, boolean hasCrc) {
        this.frameLength = frameLength;
        this.hasCrc = hasCrc;
    }

    /**
     * Decode a TM frame from the given data buffer starting at offset.
     */
    public TmFrame decode(byte[] data, int offset) {
        TmFrame frame = new TmFrame();
        frame.rawData = data;

        // Parse primary header bytes 0-1:
        // Bits 15-14: TFVN (2 bits)
        // Bits 13-4:  Spacecraft ID (10 bits)
        // Bits 3-1:   Virtual Channel ID (3 bits)
        // Bit 0:      OCF Flag (1 bit)
        int word01 = ((data[offset] & 0xFF) << 8) | (data[offset + 1] & 0xFF);

        frame.spacecraftId = (word01 >> 3) & 0x3FF;
        frame.vcid = (word01 >> 1) & 0x7;
        frame.ocfPresent = (word01 & 0x1) == 1;

        // Bytes 2-3: frame counts
        frame.mcFrameCount = data[offset + 2] & 0xFF;
        frame.vcFrameCount = data[offset + 3] & 0xFF;

        // Bytes 4-5: Transfer Frame Data Field Status
        // Bits 15:    Secondary Header Flag
        // Bit 14:     Synchronization Flag
        // Bit 13:     Packet Order Flag
        // Bits 12-11: Segment Length Identifier
        // Bits 10-0:  First Header Pointer (11 bits)
        int tfdfs = ((data[offset + 4] & 0xFF) << 8) | (data[offset + 5] & 0xFF);
        int fhp = tfdfs & 0x7FF;

        frame.firstHeaderPointer = fhp;

        // Determine data boundaries
        frame.dataStart = offset + 6;
        frame.dataEnd = offset + frameLength;

        // CRC-16 is the last 2 bytes
        if (hasCrc) {
            frame.dataEnd -= 2;
            int computedCrc = CrcCalculator.compute(data, offset, frame.dataEnd - offset);
            int frameCrc = ((data[frame.dataEnd] & 0xFF) << 8) | (data[frame.dataEnd + 1] & 0xFF);
            frame.crcValid = (computedCrc == frameCrc);
        } else {
            frame.crcValid = true;
        }

        // OCF is the 4 bytes before CRC (if present)
        if (frame.ocfPresent) {
            frame.dataEnd -= 4;
            frame.ocf = ((data[frame.dataEnd] & 0xFF) << 24) |
                       ((data[frame.dataEnd + 1] & 0xFF) << 16) |
                       ((data[frame.dataEnd + 2] & 0xFF) << 8) |
                       (data[frame.dataEnd + 3] & 0xFF);
        }

        return frame;
    }
}
