/**
 * CCSDS TM pseudo-randomizer per CCSDS 131.0-B-3.
 * Generates the 255-byte pseudo-random sequence and XORs frame data.
 */
public class Randomizer {
    private static final byte[] sequence = new byte[255];

    static {
        int lfsr = 0xFF;
        for (int i = 0; i < 255; i++) {
            sequence[i] = 0;
            for (int j = 0; j < 8; j++) {
                sequence[i] = (byte) ((sequence[i] << 1) | (lfsr & 1));
                int bit = ((lfsr >> 0) ^ (lfsr >> 2) ^ (lfsr >> 5) ^ (lfsr >> 7)) & 1;
                lfsr = (lfsr >> 1) | (bit << 7);
            }
        }
    }

    /**
     * Derandomize (or randomize) data by XORing with the CCSDS TM pseudo-random sequence.
     * The sequence resets at the beginning of each frame.
     */
    public static void derandomize(byte[] data, int offset, int length) {
        int j = 0;
        for (int i = offset; i < offset + length; i++) {
            data[i] = (byte) (data[i] ^ sequence[j]);
            j++;
            if (j == 255) j = 0;
        }
    }
}
