import java.io.*;
import java.nio.file.*;
import java.util.*;

/**
 * Minimal JSON reader/writer for flat JSON objects containing
 * numbers, strings, and arrays of numbers. Provided as a utility.
 *
 */
public class SimpleJson {

    public static Map<String, Object> readFile(String path) throws IOException {
        String content = new String(Files.readAllBytes(Paths.get(path)));
        return parse(content);
    }

    private static Map<String, Object> parse(String json) {
        Map<String, Object> result = new LinkedHashMap<>();
        json = json.trim();
        if (json.startsWith("{")) json = json.substring(1);
        if (json.endsWith("}")) json = json.substring(0, json.length() - 1);

        int i = 0;
        while (i < json.length()) {
            int keyStart = json.indexOf('"', i);
            if (keyStart < 0) break;
            int keyEnd = json.indexOf('"', keyStart + 1);
            if (keyEnd < 0) break;
            String key = json.substring(keyStart + 1, keyEnd);

            int colon = json.indexOf(':', keyEnd + 1);
            if (colon < 0) break;

            int valStart = colon + 1;
            while (valStart < json.length() && Character.isWhitespace(json.charAt(valStart)))
                valStart++;
            if (valStart >= json.length()) break;

            char ch = json.charAt(valStart);
            if (ch == '[') {
                int depth = 1;
                int arrEnd = valStart + 1;
                while (arrEnd < json.length() && depth > 0) {
                    if (json.charAt(arrEnd) == '[') depth++;
                    else if (json.charAt(arrEnd) == ']') depth--;
                    arrEnd++;
                }
                String arrStr = json.substring(valStart + 1, arrEnd - 1).trim();
                if (arrStr.isEmpty()) {
                    result.put(key, new double[0]);
                } else {
                    String[] parts = arrStr.split(",");
                    double[] arr = new double[parts.length];
                    for (int j = 0; j < parts.length; j++) {
                        arr[j] = Double.parseDouble(parts[j].trim());
                    }
                    result.put(key, arr);
                }
                i = arrEnd;
            } else if (ch == '"') {
                int strEnd = json.indexOf('"', valStart + 1);
                result.put(key, json.substring(valStart + 1, strEnd));
                i = strEnd + 1;
            } else {
                int numEnd = valStart;
                while (numEnd < json.length() && json.charAt(numEnd) != ','
                        && json.charAt(numEnd) != '}' && json.charAt(numEnd) != '\n'
                        && json.charAt(numEnd) != '\r') {
                    numEnd++;
                }
                String numStr = json.substring(valStart, numEnd).trim();
                result.put(key, Double.parseDouble(numStr));
                i = numEnd;
            }
        }
        return result;
    }

    public static void writeFile(String path, Map<String, Object> data) throws IOException {
        try (PrintWriter w = new PrintWriter(new FileWriter(path))) {
            w.println("{");
            int count = 0;
            int total = data.size();
            for (Map.Entry<String, Object> e : data.entrySet()) {
                count++;
                String comma = count < total ? "," : "";
                Object val = e.getValue();
                if (val instanceof double[]) {
                    double[] arr = (double[]) val;
                    StringBuilder sb = new StringBuilder("[");
                    for (int j = 0; j < arr.length; j++) {
                        if (j > 0) sb.append(", ");
                        sb.append(fmtDouble(arr[j]));
                    }
                    sb.append("]");
                    w.println("  \"" + e.getKey() + "\": " + sb + comma);
                } else if (val instanceof Number) {
                    w.println("  \"" + e.getKey() + "\": " + fmtDouble(((Number) val).doubleValue()) + comma);
                } else {
                    w.println("  \"" + e.getKey() + "\": \"" + val + "\"" + comma);
                }
            }
            w.println("}");
        }
    }

    private static String fmtDouble(double d) {
        if (Double.isNaN(d)) return "\"NaN\"";
        if (Double.isInfinite(d)) return d > 0 ? "\"Infinity\"" : "\"-Infinity\"";
        return String.format(Locale.US, "%.15e", d);
    }

    public static double getDouble(Map<String, Object> m, String key) {
        return ((Number) m.get(key)).doubleValue();
    }

    public static int getInt(Map<String, Object> m, String key) {
        return ((Number) m.get(key)).intValue();
    }

    public static long getLong(Map<String, Object> m, String key) {
        return ((Number) m.get(key)).longValue();
    }

    public static double[] getDoubleArray(Map<String, Object> m, String key) {
        return (double[]) m.get(key);
    }
}
