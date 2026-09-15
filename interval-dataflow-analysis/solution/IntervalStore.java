package dataflow;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Maps variable names to Interval values. Represents the abstract state at a program point.
 * A null IntervalStore represents unreachable code.
 */
public class IntervalStore {
    private final Map<String, Interval> map;

    public IntervalStore(List<String> vars) {
        this.map = new LinkedHashMap<>();
        for (String v : vars) {
            map.put(v, Interval.BOT);
        }
    }

    private IntervalStore(Map<String, Interval> map) {
        this.map = new LinkedHashMap<>(map);
    }

    public Interval get(String var) {
        Interval i = map.get(var);
        return (i != null) ? i : Interval.BOT;
    }

    public void set(String var, Interval val) {
        map.put(var, val);
    }

    public IntervalStore copy() {
        return new IntervalStore(this.map);
    }

    public boolean isAllBot() {
        for (Interval i : map.values()) {
            if (!i.isBot()) return false;
        }
        return true;
    }

    /**
     * Component-wise join. null represents unreachable.
     */
    public static IntervalStore join(IntervalStore a, IntervalStore b) {
        if (a == null) return (b != null) ? b.copy() : null;
        if (b == null) return a.copy();
        IntervalStore result = a.copy();
        for (String v : result.map.keySet()) {
            result.map.put(v, a.get(v).join(b.get(v)));
        }
        return result;
    }

    /**
     * Component-wise widening.
     */
    public IntervalStore widen(IntervalStore newer) {
        if (newer == null) return this.copy();
        IntervalStore result = this.copy();
        for (String v : result.map.keySet()) {
            result.map.put(v, this.get(v).widen(newer.get(v)));
        }
        return result;
    }

    /**
     * Component-wise narrowing.
     */
    public IntervalStore narrow(IntervalStore newer) {
        if (newer == null) return null;
        IntervalStore result = this.copy();
        for (String v : result.map.keySet()) {
            result.map.put(v, this.get(v).narrow(newer.get(v)));
        }
        return result;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof IntervalStore)) return false;
        IntervalStore other = (IntervalStore) o;
        return this.map.equals(other.map);
    }

    @Override
    public int hashCode() {
        return map.hashCode();
    }

    public List<String> variables() {
        return new java.util.ArrayList<>(map.keySet());
    }
}
