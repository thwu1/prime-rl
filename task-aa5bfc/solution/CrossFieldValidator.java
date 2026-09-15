package swift;


public class CrossFieldValidator {

    public static void validateAll(Mt103Message msg) {
        validateC1(msg);
        validateC2(msg);
        validateC3(msg);
        validateC4(msg);
        validateC5(msg);
        validateC6(msg);
    }

    /**
     * C1: If :33B: currency differs from :32A: currency, then :36: is mandatory.
     * FIX: Actually compare currencies before requiring :36:.
     */
    private static void validateC1(Mt103Message msg) {
        if (!msg.hasField("33B")) return;

        String field32A = msg.getFieldValue("32A");
        String field33B = msg.getFieldValue("33B");
        if (field32A == null || field33B == null) return;

        // Extract currency from :32A: (positions 6-8)
        if (field32A.length() < 9) return;
        String currency32A = field32A.substring(6, 9);

        // Extract currency from :33B: (first 3 chars)
        if (field33B.length() < 3) return;
        String currency33B = field33B.substring(0, 3);

        // If currencies differ, :36: is mandatory
        if (!currency32A.equals(currency33B)) {
            if (!msg.hasField("36")) {
                msg.addError(":36:", "C1_VIOLATION", "Field :36: is required when :33B: currency differs from :32A: currency");
            }
        }
    }

    /**
     * C2: If :33B: currency equals :32A: currency, then :36: must NOT be present.
     */
    private static void validateC2(Mt103Message msg) {
        if (!msg.hasField("33B")) return;

        String field32A = msg.getFieldValue("32A");
        String field33B = msg.getFieldValue("33B");
        if (field32A == null || field33B == null) return;

        if (field32A.length() < 9) return;
        String currency32A = field32A.substring(6, 9);

        if (field33B.length() < 3) return;
        String currency33B = field33B.substring(0, 3);

        // If currencies are the same, :36: must NOT be present
        if (currency32A.equals(currency33B)) {
            if (msg.hasField("36")) {
                msg.addError(":36:", "C2_VIOLATION", "Field :36: must not be present when :33B: currency equals :32A: currency");
            }
        }
    }

    /**
     * C3: If :71A: is BEN, then :71F: must not be present.
     * FIX: Correct logic.
     */
    private static void validateC3(Mt103Message msg) {
        String chargeCode = msg.getFieldValue("71A");
        if (chargeCode == null) return;

        if ("BEN".equals(chargeCode.trim()) && msg.hasField("71F")) {
            msg.addError(":71F:", "C3_VIOLATION", "Field :71F: not allowed when :71A: is BEN");
        }
    }

    /**
     * C4: If :71A: is OUR, both :71F: and :71G: are allowed. No validation needed.
     */
    private static void validateC4(Mt103Message msg) {
        // OUR is permissive
    }

    /**
     * C5: If :71A: is SHA, then :71G: must not be present.
     */
    private static void validateC5(Mt103Message msg) {
        String chargeCode = msg.getFieldValue("71A");
        if (chargeCode == null) return;

        if ("SHA".equals(chargeCode.trim()) && msg.hasField("71G")) {
            msg.addError(":71G:", "C5_VIOLATION", "Field :71G: must not be present when :71A: is SHA");
        }
    }

    /**
     * C6: :72: lines must start with / for first line and // for continuations.
     * Code words max 8 chars.
     */
    private static void validateC6(Mt103Message msg) {
        if (!msg.hasField("72")) return;

        String value = msg.getFieldValue("72");
        if (value == null) return;

        String[] lines = value.split("\\n");
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (i == 0) {
                // First line must start with /
                if (!line.startsWith("/")) {
                    msg.addError(":72:", "C6_VIOLATION", "First line of :72: must start with /");
                } else {
                    // Validate code word length
                    int nextSlash = line.indexOf("/", 1);
                    if (nextSlash > 0) {
                        String codeWord = line.substring(1, nextSlash);
                        if (codeWord.length() > 8) {
                            msg.addError(":72:", "C6_VIOLATION", "Code word in :72: exceeds 8 characters: " + codeWord);
                        }
                    }
                }
            } else {
                // Continuation lines must start with //
                if (!line.startsWith("//")) {
                    msg.addError(":72:", "C6_VIOLATION", "Continuation line of :72: must start with //");
                }
            }
        }
    }
}
