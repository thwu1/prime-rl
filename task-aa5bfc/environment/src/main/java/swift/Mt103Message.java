package swift;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;


public class Mt103Message {
    public String block1 = "";
    public String block2 = "";
    public String block3 = "";
    public String block4Raw = "";
    public String block5 = "";

    // Extracted from block 1
    public String senderBic = "";
    // Extracted from block 2
    public String receiverBic = "";

    // Parsed fields from block 4 - tag -> list of values (some fields are repetitive)
    public Map<String, List<String>> fields = new HashMap<>();

    public List<ValidationError> errors = new ArrayList<>();
    public boolean valid = true;
    public boolean stpCompliant = false;

    public String reference = "";
    public String settlementAmount = "";
    public String settlementCurrency = "";

    public void addField(String tag, String value) {
        fields.computeIfAbsent(tag, k -> new ArrayList<>()).add(value);
    }

    public String getFieldValue(String tag) {
        List<String> vals = fields.get(tag);
        if (vals != null && !vals.isEmpty()) {
            return vals.get(0);
        }
        return null;
    }

    public List<String> getFieldValues(String tag) {
        return fields.getOrDefault(tag, new ArrayList<>());
    }

    public boolean hasField(String tag) {
        return fields.containsKey(tag) && !fields.get(tag).isEmpty();
    }

    public void addError(String field, String rule, String message) {
        errors.add(new ValidationError(field, rule, message));
        valid = false;
    }

    public String toJson(int index) {
        StringBuilder sb = new StringBuilder();
        sb.append("  {\n");
        sb.append("    \"index\": ").append(index).append(",\n");
        sb.append("    \"reference\": \"").append(jsonEscape(reference)).append("\",\n");
        sb.append("    \"valid\": ").append(valid).append(",\n");
        sb.append("    \"stp_compliant\": ").append(stpCompliant).append(",\n");
        sb.append("    \"errors\": [");
        for (int i = 0; i < errors.size(); i++) {
            if (i > 0) sb.append(", ");
            sb.append(errors.get(i).toJson());
        }
        sb.append("],\n");
        sb.append("    \"settlement_amount\": \"").append(jsonEscape(settlementAmount)).append("\",\n");
        sb.append("    \"settlement_currency\": \"").append(jsonEscape(settlementCurrency)).append("\",\n");
        sb.append("    \"sender_bic\": \"").append(jsonEscape(senderBic)).append("\",\n");
        sb.append("    \"receiver_bic\": \"").append(jsonEscape(receiverBic)).append("\"\n");
        sb.append("  }");
        return sb.toString();
    }

    private String jsonEscape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
    }
}
