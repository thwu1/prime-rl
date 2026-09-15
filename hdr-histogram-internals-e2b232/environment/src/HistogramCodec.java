
import java.io.*;
import java.util.zip.*;
import java.util.Base64;

/**
 * Encodes and decodes HdrHistogram instances to/from a compact string representation.
 *
 * Wire format (before compression):
 *   - 8 bytes: lowestDiscernibleValue (big-endian long)
 *   - 8 bytes: highestTrackableValue (big-endian long)
 *   - 4 bytes: numberOfSignificantValueDigits (big-endian int)
 *   - Remaining bytes: counts array encoded as ZigZag varints with zero-run compression:
 *       * Consecutive zero-count slots are collapsed into a single negative varint
 *         whose absolute value equals the run length.
 *       * Non-zero counts are encoded as positive ZigZag varints.
 *
 * ZigZag encoding maps signed longs to unsigned: zigzag(n) = (n &lt;&lt; 1) ^ (n &gt;&gt; 63)
 * Varint encoding: 7 bits per byte, MSB set if more bytes follow (little-endian byte order).
 *
 * The wire-format bytes are DEFLATE-compressed, then Base64-encoded (standard alphabet).
 *
 * All methods marked // TODO must be implemented.
 */
public class HistogramCodec {

    /**
     * Encode a histogram to a compact Base64 string.
     * Writes the header (ldv, htv, digits), followed by the counts array
     * using zero-run compressed ZigZag varints, then DEFLATE-compresses
     * and Base64-encodes the result.
     *
     * @param histogram the histogram to encode
     * @return Base64-encoded, DEFLATE-compressed representation
     *
     * // TODO: Implement this method
     */
    public static String encode(HdrHistogram histogram) {
        throw new UnsupportedOperationException("TODO: implement encode");
    }

    /**
     * Decode a Base64 string back into an HdrHistogram with all counts,
     * totalCount, and min/max tracking restored.
     *
     * @param encoded the Base64 string produced by encode()
     * @return a new HdrHistogram with the decoded data
     *
     * // TODO: Implement this method
     */
    public static HdrHistogram decode(String encoded) {
        throw new UnsupportedOperationException("TODO: implement decode");
    }

    /**
     * Encode a signed long value using ZigZag encoding.
     *
     * // TODO: Implement this method
     */
    static long zigZagEncode(long n) {
        throw new UnsupportedOperationException("TODO: implement zigZagEncode");
    }

    /**
     * Decode a ZigZag-encoded value back to a signed long.
     *
     * // TODO: Implement this method
     */
    static long zigZagDecode(long n) {
        throw new UnsupportedOperationException("TODO: implement zigZagDecode");
    }

    /**
     * Write a signed long as a ZigZag-encoded varint to the output stream.
     * First apply ZigZag encoding to obtain an unsigned representation,
     * then write as unsigned varint (7 data bits per byte, MSB set if more bytes follow).
     *
     * // TODO: Implement this method
     */
    static void writeZigZagVarint(OutputStream out, long value) throws IOException {
        throw new UnsupportedOperationException("TODO: implement writeZigZagVarint");
    }

    /**
     * Read a ZigZag-encoded varint from the input stream and return the decoded signed long.
     *
     * @return the decoded signed long value
     * @throws IOException on stream error or unexpected end of stream
     *
     * // TODO: Implement this method
     */
    static long readZigZagVarint(InputStream in) throws IOException {
        throw new UnsupportedOperationException("TODO: implement readZigZagVarint");
    }

    /**
     * Verification entry point. Called by 'make verify'.
     * Creates a test histogram, encodes it, decodes it, and verifies statistics match.
     * Prints "ROUNDTRIP_OK" and exits 0 on success, exits 1 on failure.
     */
    public static void main(String[] args) {
        if (args.length == 0 || !args[0].equals("roundtrip")) {
            System.err.println("Usage: java HistogramCodec roundtrip");
            System.exit(1);
        }

        HdrHistogram original = new HdrHistogram(1, 3600000000L, 3);
        long[] testValues = {100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000, 3000000000L};
        int[] testCounts  = {400, 200, 150, 100, 60, 40, 25, 15, 8, 2};
        for (int i = 0; i < testValues.length; i++) {
            original.recordValueWithCount(testValues[i], testCounts[i]);
        }

        String encoded = encode(original);
        HdrHistogram decoded = decode(encoded);

        boolean pass = true;
        if (decoded.getTotalCount() != original.getTotalCount()) {
            System.err.println("FAIL: totalCount " + decoded.getTotalCount() + " != " + original.getTotalCount());
            pass = false;
        }
        if (decoded.getMaxValue() != original.getMaxValue()) {
            System.err.println("FAIL: maxValue mismatch: " + decoded.getMaxValue() + " != " + original.getMaxValue());
            pass = false;
        }
        if (decoded.getMinValue() != original.getMinValue()) {
            System.err.println("FAIL: minValue mismatch: " + decoded.getMinValue() + " != " + original.getMinValue());
            pass = false;
        }
        if (Math.abs(decoded.getMean() - original.getMean()) > 0.001) {
            System.err.println("FAIL: mean mismatch: " + decoded.getMean() + " != " + original.getMean());
            pass = false;
        }

        if (pass) {
            System.out.println("ROUNDTRIP_OK");
            System.exit(0);
        } else {
            System.exit(1);
        }
    }
}
