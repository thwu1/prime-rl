package swift;


public class ValidationError {
    public String field;
    public String rule;
    public String message;

    public ValidationError(String field, String rule, String message) {
        this.field = field;
        this.rule = rule;
        this.message = message;
    }

    public String toJson() {
        return "{\"field\": \"" + jsonEscape(field) + "\", \"rule\": \"" + jsonEscape(rule) + "\", \"message\": \"" + jsonEscape(message) + "\"}";
    }

    private String jsonEscape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
    }
}
