/**
 * CRC-16-CCITT calculator using polynomial 0x1021.
 * Used for TM frame error detection per CCSDS 132.0-B-3.
 */
public class CrcCalculator {
    private static final int POLYNOMIAL = 0x1021;
    private static final int[] table = new int[256];

    static {
        for (int i = 0; i < 256; i++) {
            int remainder = i << 8;
            for (int j = 0; j < 8; j++) {
                if ((remainder & 0x8000) != 0) {
                    remainder = ((remainder << 1) ^ POLYNOMIAL) & 0xFFFF;
                } else {
                    remainder = (remainder << 1) & 0xFFFF;
                }
            }
            table[i] = remainder;
        }
    }

    /**
     * Compute CRC-16-CCITT over the given data range.
     */
    public static int compute(byte[] data, int offset, int length) {
        int crc = 0x0000;
        for (int i = offset; i < offset + length; i++) {
            int idx = ((data[i] & 0xFF) ^ (crc >> 8)) & 0xFF;
            crc = (table[idx] ^ (crc << 8)) & 0xFFFF;
        }
        return crc;
    }
}
