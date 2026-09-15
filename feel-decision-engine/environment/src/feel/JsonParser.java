package feel;

import java.math.BigDecimal;
import java.util.*;

public class JsonParser {
    private String input;
    private int pos;

    public static Object parse(String json) {
        return new JsonParser(json.trim()).parseValue();
    }

    private JsonParser(String input) {
        this.input = input;
        this.pos = 0;
    }

    private void skipWhitespace() {
        while (pos < input.length() && Character.isWhitespace(input.charAt(pos))) {
            pos++;
        }
    }

    private char peek() {
        skipWhitespace();
        return pos < input.length() ? input.charAt(pos) : 0;
    }

    private char next() {
        skipWhitespace();
        return input.charAt(pos++);
    }

    private Object parseValue() {
        char c = peek();
        if (c == '{') return parseObject();
        if (c == '[') return parseArray();
        if (c == '"') return parseString();
        if (c == 't' || c == 'f') return parseBoolean();
        if (c == 'n') return parseNull();
        return parseNumber();
    }

    private Map<String, Object> parseObject() {
        Map<String, Object> map = new LinkedHashMap<>();
        next(); // {
        if (peek() != '}') {
            do {
                String key = parseString();
                next(); // :
                Object value = parseValue();
                map.put(key, value);
            } while (peek() == ',' && next() == ',');
        }
        next(); // }
        return map;
    }

    private List<Object> parseArray() {
        List<Object> list = new ArrayList<>();
        next(); // [
        if (peek() != ']') {
            do {
                list.add(parseValue());
            } while (peek() == ',' && next() == ',');
        }
        next(); // ]
        return list;
    }

    private String parseString() {
        next(); // opening "
        StringBuilder sb = new StringBuilder();
        while (input.charAt(pos) != '"') {
            if (input.charAt(pos) == '\\') {
                pos++;
                char esc = input.charAt(pos);
                switch (esc) {
                    case '"': sb.append('"'); break;
                    case '\\': sb.append('\\'); break;
                    case '/': sb.append('/'); break;
                    case 'n': sb.append('\n'); break;
                    case 't': sb.append('\t'); break;
                    case 'r': sb.append('\r'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    default: sb.append(esc);
                }
            } else {
                sb.append(input.charAt(pos));
            }
            pos++;
        }
        pos++; // closing "
        return sb.toString();
    }

    private BigDecimal parseNumber() {
        skipWhitespace();
        int start = pos;
        if (pos < input.length() && input.charAt(pos) == '-') pos++;
        while (pos < input.length() && Character.isDigit(input.charAt(pos))) pos++;
        if (pos < input.length() && input.charAt(pos) == '.') {
            pos++;
            while (pos < input.length() && Character.isDigit(input.charAt(pos))) pos++;
        }
        if (pos < input.length() && (input.charAt(pos) == 'e' || input.charAt(pos) == 'E')) {
            pos++;
            if (pos < input.length() && (input.charAt(pos) == '+' || input.charAt(pos) == '-')) pos++;
            while (pos < input.length() && Character.isDigit(input.charAt(pos))) pos++;
        }
        return new BigDecimal(input.substring(start, pos));
    }

    private boolean parseBoolean() {
        if (input.startsWith("true", pos)) { pos += 4; return true; }
        if (input.startsWith("false", pos)) { pos += 5; return false; }
        throw new RuntimeException("Expected boolean at position " + pos);
    }

    private Object parseNull() {
        if (input.startsWith("null", pos)) { pos += 4; return null; }
        throw new RuntimeException("Expected null at position " + pos);
    }

    // JSON serializer
    @SuppressWarnings("unchecked")
    public static String toJson(Object value) {
        if (value == null) return "null";
        if (value instanceof Boolean) return value.toString();
        if (value instanceof BigDecimal) {
            BigDecimal bd = (BigDecimal) value;
            return bd.stripTrailingZeros().toPlainString();
        }
        if (value instanceof String) {
            return "\"" + escapeString((String) value) + "\"";
        }
        if (value instanceof List) {
            List<?> list = (List<?>) value;
            StringBuilder sb = new StringBuilder("[");
            for (int i = 0; i < list.size(); i++) {
                if (i > 0) sb.append(", ");
                sb.append(toJson(list.get(i)));
            }
            return sb.append("]").toString();
        }
        if (value instanceof Map) {
            Map<String, Object> map = (Map<String, Object>) value;
            StringBuilder sb = new StringBuilder("{");
            boolean first = true;
            for (Map.Entry<String, Object> entry : map.entrySet()) {
                if (!first) sb.append(", ");
                first = false;
                sb.append("\"").append(escapeString(entry.getKey())).append("\": ");
                sb.append(toJson(entry.getValue()));
            }
            return sb.append("}").toString();
        }
        return value.toString();
    }

    private static String escapeString(String s) {
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
