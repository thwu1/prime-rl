package feel;

import java.io.*;
import java.util.*;

public class Main {

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java feel.Main <table.json> [input.json]");
            System.exit(1);
        }

        String tableJson = readFile(args[0]);
        Map<String, Object> tableDef = (Map<String, Object>) JsonParser.parse(tableJson);

        String inputJson;
        if (args.length >= 2) {
            inputJson = readFile(args[1]);
        } else {
            inputJson = readStdin();
        }

        Map<String, Object> inputData = (Map<String, Object>) JsonParser.parse(inputJson);

        try {
            Object result = DecisionTableEngine.evaluate(tableDef, inputData);
            Object jsonResult = convertToJson(result);
            System.out.println(JsonParser.toJson(jsonResult));
        } catch (RuntimeException e) {
            Map<String, Object> error = new LinkedHashMap<>();
            error.put("_error", e.getMessage() != null ? e.getMessage() : e.getClass().getName());
            System.out.println(JsonParser.toJson(error));
        }
    }

    @SuppressWarnings("unchecked")
    private static Object convertToJson(Object result) {
        if (result == null) {
            return null;
        }
        if (result instanceof Map) {
            Map<String, FeelValue> map = (Map<String, FeelValue>) result;
            Map<String, Object> jsonMap = new LinkedHashMap<>();
            for (Map.Entry<String, FeelValue> entry : map.entrySet()) {
                jsonMap.put(entry.getKey(), entry.getValue().toJsonValue());
            }
            return jsonMap;
        }
        if (result instanceof List) {
            List<?> list = (List<?>) result;
            List<Object> jsonList = new ArrayList<>();
            for (Object item : list) {
                jsonList.add(convertToJson(item));
            }
            return jsonList;
        }
        return result;
    }

    private static String readFile(String path) throws IOException {
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (sb.length() > 0) sb.append("\n");
                sb.append(line);
            }
        }
        return sb.toString();
    }

    private static String readStdin() throws IOException {
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(System.in))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (sb.length() > 0) sb.append("\n");
                sb.append(line);
            }
        }
        return sb.toString();
    }
}
