/**
 * Represents a decoded CCSDS TM Transfer Frame per CCSDS 132.0-B-2.
 */
public class TmFrame {
    public int spacecraftId;
    public int vcid;
    public int mcFrameCount;
    public int vcFrameCount;
    public int firstHeaderPointer;
    public boolean ocfPresent;
    public int ocf;
    public boolean crcValid;
    public int dataStart;
    public int dataEnd;
    public byte[] rawData;
}
