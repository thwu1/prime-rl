
import java.io.*;
import java.util.zip.*;
import java.util.Base64;

public class HistogramCodec {

    public static String encode(HdrHistogram histogram) {
        try {
            ByteArrayOutputStream rawBaos = new ByteArrayOutputStream();
            DataOutputStream dos = new DataOutputStream(rawBaos);

            dos.writeLong(histogram.lowestDiscernibleValue);
            dos.writeLong(histogram.highestTrackableValue);
            dos.writeInt(histogram.numberOfSignificantValueDigits);

            ByteArrayOutputStream countsBytes = new ByteArrayOutputStream();
            int zeroRun = 0;
            for (int i = 0; i < histogram.countsArrayLength; i++) {
                long count = histogram.counts[i];
                if (count == 0) {
                    zeroRun++;
                } else {
                    if (zeroRun > 0) {
                        writeZigZagVarint(countsBytes, -zeroRun);
                        zeroRun = 0;
                    }
                    writeZigZagVarint(countsBytes, count);
                }
            }
            if (zeroRun > 0) {
                writeZigZagVarint(countsBytes, -zeroRun);
            }

            dos.write(countsBytes.toByteArray());
            dos.flush();

            byte[] raw = rawBaos.toByteArray();
            ByteArrayOutputStream compressed = new ByteArrayOutputStream();
            DeflaterOutputStream deflater = new DeflaterOutputStream(compressed);
            deflater.write(raw);
            deflater.finish();
            deflater.close();

            return Base64.getEncoder().encodeToString(compressed.toByteArray());
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }

    public static HdrHistogram decode(String encoded) {
        try {
            byte[] compressed = Base64.getDecoder().decode(encoded);

            ByteArrayOutputStream decompressed = new ByteArrayOutputStream();
            InflaterInputStream inflater = new InflaterInputStream(new ByteArrayInputStream(compressed));
            byte[] buf = new byte[4096];
            int n;
            while ((n = inflater.read(buf)) != -1) {
                decompressed.write(buf, 0, n);
            }
            inflater.close();

            byte[] data = decompressed.toByteArray();
            DataInputStream dis = new DataInputStream(new ByteArrayInputStream(data));
            long lowestDiscernibleValue = dis.readLong();
            long highestTrackableValue = dis.readLong();
            int numberOfSignificantValueDigits = dis.readInt();

            HdrHistogram histogram = new HdrHistogram(lowestDiscernibleValue,
                    highestTrackableValue, numberOfSignificantValueDigits);

            ByteArrayInputStream countsStream = new ByteArrayInputStream(data, 20, data.length - 20);
            int index = 0;
            while (countsStream.available() > 0 && index < histogram.countsArrayLength) {
                long value = readZigZagVarint(countsStream);
                if (value < 0) {
                    index += (int) (-value);
                } else {
                    long histValue = histogram.valueFromIndex(index);
                    histogram.recordValueWithCount(histValue, value);
                    index++;
                }
            }

            return histogram;
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }

    static long zigZagEncode(long n) {
        return (n << 1) ^ (n >> 63);
    }

    static long zigZagDecode(long n) {
        return (n >>> 1) ^ -(n & 1);
    }

    static void writeZigZagVarint(OutputStream out, long value) throws IOException {
        long unsigned = zigZagEncode(value);
        while ((unsigned & ~0x7FL) != 0) {
            out.write((int) ((unsigned & 0x7F) | 0x80));
            unsigned >>>= 7;
        }
        out.write((int) (unsigned & 0x7F));
    }

    static long readZigZagVarint(InputStream in) throws IOException {
        long unsigned = 0;
        int shift = 0;
        int b;
        do {
            b = in.read();
            if (b < 0) throw new IOException("Unexpected end of stream");
            unsigned |= (long) (b & 0x7F) << shift;
            shift += 7;
        } while ((b & 0x80) != 0);
        return zigZagDecode(unsigned);
    }

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
