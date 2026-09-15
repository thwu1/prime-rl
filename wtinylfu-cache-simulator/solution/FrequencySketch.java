package wtinylfu;

public final class FrequencySketch {

    static final long RESET_MASK = 0x7777777777777777L;
    static final long ONE_MASK = 0x1111111111111111L;
    static final int MIN_SKETCH_SIZE = 256;

    int sampleSize;
    int blockMask;
    long[] table;
    int size;

    public void ensureCapacity(int maximumSize) {
        int maximum = Math.max(maximumSize, MIN_SKETCH_SIZE);
        int n = ceilingPowerOfTwo(maximum);
        table = new long[n];
        sampleSize = (int) Math.min(10L * maximum, Integer.MAX_VALUE);
        blockMask = (n >>> 3) - 1;
        size = 0;
    }

    static int ceilingPowerOfTwo(int x) {
        int n = -1 >>> Integer.numberOfLeadingZeros(x - 1);
        return (n < 0) ? 1 : n + 1;
    }

    public int frequency(int key) {
        if (table == null) return 0;
        int frequency = Integer.MAX_VALUE;
        int blockHash = spread(key);
        int counterHash = rehash(blockHash);
        int block = (blockHash & blockMask) << 3;
        for (int i = 0; i < 4; i++) {
            int h = counterHash >>> (i << 3);
            int index = (h >>> 1) & 15;
            int offset = h & 1;
            int slot = block + offset + (i << 1);
            int count = (int) ((table[slot] >>> (index << 2)) & 0xfL);
            frequency = Math.min(frequency, count);
        }
        return frequency;
    }

    public void increment(int key) {
        if (table == null) return;
        int blockHash = spread(key);
        int counterHash = rehash(blockHash);
        int block = (blockHash & blockMask) << 3;
        boolean added = false;
        for (int i = 0; i < 4; i++) {
            int h = counterHash >>> (i << 3);
            int index = (h >>> 1) & 15;
            int offset = h & 1;
            int slot = block + offset + (i << 1);
            added |= incrementAt(slot, index);
        }
        if (added && (++size == sampleSize)) {
            reset();
        }
    }

    static int spread(int x) {
        x ^= x >>> 17;
        x *= 0xed5ad4bb;
        x ^= x >>> 11;
        x *= 0xac4c1b51;
        x ^= x >>> 15;
        return x;
    }

    static int rehash(int x) {
        x *= 0x31848bab;
        x ^= x >>> 14;
        return x;
    }

    boolean incrementAt(int i, int j) {
        int offset = j << 2;
        long mask = (0xfL << offset);
        if ((table[i] & mask) != mask) {
            table[i] += (1L << offset);
            return true;
        }
        return false;
    }

    void reset() {
        long count = 0;
        for (int i = 0; i < table.length; i++) {
            count += Long.bitCount(table[i] & ONE_MASK);
            table[i] = (table[i] >>> 1) & RESET_MASK;
        }
        size = (int) ((size - (count >>> 2)) >>> 1);
    }
}
