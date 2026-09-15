package dataflow;

/**
 * Represents an integer interval [lo, hi] or bottom (empty set).
 */
public class Interval {
    public static final long NEG_INF = Long.MIN_VALUE / 4;
    public static final long POS_INF = Long.MAX_VALUE / 4;

    public static final Interval BOT = new Interval(0, 0, true);
    public static final Interval TOP = new Interval(NEG_INF, POS_INF, false);

    public final long lo;
    public final long hi;
    private final boolean bot;

    private Interval(long lo, long hi, boolean bot) {
        this.lo = lo;
        this.hi = hi;
        this.bot = bot;
    }

    public static Interval of(long lo, long hi) {
        if (lo > hi) return BOT;
        return new Interval(clamp(lo), clamp(hi), false);
    }

    public static Interval constant(long v) {
        return new Interval(v, v, false);
    }

    public boolean isBot() { return bot; }

    public Interval join(Interval other) {
        if (this.bot) return other;
        if (other.bot) return this;
        return of(Math.min(this.lo, other.lo), Math.max(this.hi, other.hi));
    }

    public Interval meet(Interval other) {
        if (this.bot || other.bot) return BOT;
        long newLo = Math.max(this.lo, other.lo);
        long newHi = Math.min(this.hi, other.hi);
        return of(newLo, newHi);
    }

    public Interval widen(Interval newer) {
        if (this.bot) return newer;
        if (newer.bot) return this;
        long newLo = (newer.lo < this.lo) ? NEG_INF : this.lo;
        long newHi = (newer.hi > this.hi) ? POS_INF : this.hi;
        return of(newLo, newHi);
    }

    public Interval narrow(Interval newer) {
        if (this.bot) return newer;
        if (newer.bot) return BOT;
        long newLo = (this.lo <= NEG_INF) ? newer.lo : this.lo;
        long newHi = (this.hi >= POS_INF) ? newer.hi : this.hi;
        return of(newLo, newHi);
    }

    public Interval add(Interval other) {
        if (this.bot || other.bot) return BOT;
        return of(addSafe(this.lo, other.lo), addSafe(this.hi, other.hi));
    }

    public Interval sub(Interval other) {
        if (this.bot || other.bot) return BOT;
        return of(addSafe(this.lo, negate(other.hi)), addSafe(this.hi, negate(other.lo)));
    }

    public Interval mul(Interval other) {
        if (this.bot || other.bot) return BOT;
        long a = mulSafe(this.lo, other.lo);
        long b = mulSafe(this.lo, other.hi);
        long c = mulSafe(this.hi, other.lo);
        long d = mulSafe(this.hi, other.hi);
        return of(min4(a, b, c, d), max4(a, b, c, d));
    }

    public Interval div(Interval other) {
        if (this.bot || other.bot) return BOT;
        if (other.lo <= 0 && other.hi >= 0) return TOP;
        long a = divSafe(this.lo, other.lo);
        long b = divSafe(this.lo, other.hi);
        long c = divSafe(this.hi, other.lo);
        long d = divSafe(this.hi, other.hi);
        return of(min4(a, b, c, d), max4(a, b, c, d));
    }

    private static long clamp(long v) {
        if (v < NEG_INF) return NEG_INF;
        if (v > POS_INF) return POS_INF;
        return v;
    }

    private static long negate(long v) {
        if (v <= NEG_INF) return POS_INF;
        if (v >= POS_INF) return NEG_INF;
        return -v;
    }

    private static long addSafe(long a, long b) {
        if (a <= NEG_INF || b <= NEG_INF) {
            if (a >= POS_INF || b >= POS_INF) return 0; // indeterminate
            return NEG_INF;
        }
        if (a >= POS_INF || b >= POS_INF) return POS_INF;
        return clamp(a + b);
    }

    private static long mulSafe(long a, long b) {
        if (a == 0 || b == 0) return 0;
        boolean aInf = (a <= NEG_INF || a >= POS_INF);
        boolean bInf = (b <= NEG_INF || b >= POS_INF);
        if (aInf || bInf) {
            return ((a > 0) == (b > 0)) ? POS_INF : NEG_INF;
        }
        long product = a * b;
        if (a != 0 && product / a != b) {
            return ((a > 0) == (b > 0)) ? POS_INF : NEG_INF;
        }
        return clamp(product);
    }

    private static long divSafe(long a, long b) {
        if (b == 0) return POS_INF;
        if (a == 0) return 0;
        boolean aInf = (a <= NEG_INF || a >= POS_INF);
        boolean bInf = (b <= NEG_INF || b >= POS_INF);
        if (aInf && bInf) return ((a > 0) == (b > 0)) ? POS_INF : NEG_INF;
        if (aInf) return ((a > 0) == (b > 0)) ? POS_INF : NEG_INF;
        if (bInf) return 0;
        return clamp(a / b);
    }

    private static long min4(long a, long b, long c, long d) {
        return Math.min(Math.min(a, b), Math.min(c, d));
    }

    private static long max4(long a, long b, long c, long d) {
        return Math.max(Math.max(a, b), Math.max(c, d));
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Interval)) return false;
        Interval other = (Interval) o;
        if (this.bot && other.bot) return true;
        if (this.bot || other.bot) return false;
        return this.lo == other.lo && this.hi == other.hi;
    }

    @Override
    public int hashCode() {
        if (bot) return 0;
        return Long.hashCode(lo) * 31 + Long.hashCode(hi);
    }

    @Override
    public String toString() {
        if (bot) return "bot";
        String loStr = (lo <= NEG_INF) ? "-inf" : String.valueOf(lo);
        String hiStr = (hi >= POS_INF) ? "inf" : String.valueOf(hi);
        return "[" + loStr + "," + hiStr + "]";
    }
}
