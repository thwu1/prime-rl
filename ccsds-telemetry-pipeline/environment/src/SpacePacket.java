/**
 * Represents a decoded CCSDS Space Packet per CCSDS 133.0-B-1.
 */
public class SpacePacket {
    public int apid;
    public int sequenceFlags;
    public int sequenceCount;
    public int dataLength;
    public byte[] userData;
}
