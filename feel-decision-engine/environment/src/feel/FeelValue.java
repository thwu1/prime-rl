package feel;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Objects;

public class FeelValue {
    public enum Type { NULL, BOOLEAN, NUMBER, STRING, DATE }

    private final Type type;
    private final Object value;

    public static final FeelValue NULL_VALUE = new FeelValue(Type.NULL, null);

    private FeelValue(Type type, Object value) {
        this.type = type;
        this.value = value;
    }

    public static FeelValue ofNull() { return NULL_VALUE; }
    public static FeelValue of(boolean b) { return new FeelValue(Type.BOOLEAN, b); }
    public static FeelValue of(BigDecimal n) { return new FeelValue(Type.NUMBER, n); }
    public static FeelValue of(long n) { return new FeelValue(Type.NUMBER, BigDecimal.valueOf(n)); }
    public static FeelValue of(String s) { return new FeelValue(Type.STRING, s); }
    public static FeelValue of(LocalDate d) { return new FeelValue(Type.DATE, d); }

    public Type getType() { return type; }
    public boolean isNull() { return type == Type.NULL; }
    public boolean asBoolean() { return (Boolean) value; }
    public BigDecimal asNumber() { return (BigDecimal) value; }
    public String asString() { return (String) value; }
    public LocalDate asDate() { return (LocalDate) value; }
    public Object getValue() { return value; }

    /**
     * Compare this value to another. Returns null if types are incompatible or either is null.
     */
    public Integer compareTo(FeelValue other) {
        if (this.isNull() || other.isNull()) return null;
        if (this.type != other.type) return null;
        switch (type) {
            case NUMBER: return asNumber().compareTo(other.asNumber());
            case STRING: return asString().compareTo(other.asString());
            case DATE: return asDate().compareTo(other.asDate());
            case BOOLEAN: return Boolean.compare(asBoolean(), other.asBoolean());
            default: return null;
        }
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof FeelValue)) return false;
        FeelValue other = (FeelValue) obj;
        if (this.type != other.type) return false;
        if (this.isNull() && other.isNull()) return true;
        if (this.type == Type.NUMBER) return asNumber().compareTo(other.asNumber()) == 0;
        return Objects.equals(this.value, other.value);
    }

    @Override
    public int hashCode() {
        if (type == Type.NUMBER && value != null) {
            return Objects.hash(type, asNumber().stripTrailingZeros());
        }
        return Objects.hash(type, value);
    }

    /**
     * Parse a FEEL literal from a JSON-provided value.
     */
    public static FeelValue fromJson(Object jsonValue) {
        if (jsonValue == null) return NULL_VALUE;
        if (jsonValue instanceof Boolean) return of((Boolean) jsonValue);
        if (jsonValue instanceof BigDecimal) return of((BigDecimal) jsonValue);
        if (jsonValue instanceof String) return of((String) jsonValue);
        return NULL_VALUE;
    }

    /**
     * Parse a FEEL literal from a string expression (used in unary tests and output entries).
     */
    public static FeelValue parseLiteral(String s) {
        s = s.trim();
        if (s.equals("null")) return NULL_VALUE;
        if (s.equals("true")) return of(true);
        if (s.equals("false")) return of(false);
        if (s.startsWith("\"") && s.endsWith("\""))
            return of(s.substring(1, s.length() - 1));
        if (s.startsWith("date(\"") && s.endsWith("\")"))
            return of(LocalDate.parse(s.substring(6, s.length() - 2)));
        try {
            return of(new BigDecimal(s));
        } catch (NumberFormatException e) {
            return of(s);
        }
    }

    /**
     * Convert to JSON-compatible value for serialization.
     */
    public Object toJsonValue() {
        switch (type) {
            case NULL: return null;
            case BOOLEAN: return (Boolean) value;
            case NUMBER: return (BigDecimal) value;
            case STRING: return (String) value;
            case DATE: return value.toString();
            default: return null;
        }
    }

    @Override
    public String toString() {
        if (isNull()) return "null";
        return value.toString();
    }
}
