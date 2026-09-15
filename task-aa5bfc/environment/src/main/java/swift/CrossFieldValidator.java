package swift;


/**
 * Cross-field validation rules (C-rules) for MT103 messages.
 *
 * BUG: Most rules are not implemented or have incorrect logic.
 */
public class CrossFieldValidator {

    /**
     * Run all cross-field validations.
     */
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
     *
     * BUG: Not comparing currencies at all, just checking if :36: exists when :33B: exists
     */
    private static void validateC1(Mt103Message msg) {
        if (!msg.hasField("33B")) return;

        // BUG: Should extract and compare the currency codes from :33B: and :32A:
        // Currently just checks if :36: is present whenever :33B: is present
        if (!msg.hasField("36")) {
            msg.addError(":36:", "C1_VIOLATION", "Field :36: is required when :33B: is present");
        }
    }

    /**
     * C2: If :33B: currency equals :32A: currency, then :36: must NOT be present.
     *
     * BUG: Not implemented at all
     */
    private static void validateC2(Mt103Message msg) {
        // TODO: implement C2 rule
    }

    /**
     * C3: If :71A: is BEN, then :71F: must not be present.
     *
     * BUG: Logic is inverted - checks if :71F: IS present when NOT BEN
     */
    private static void validateC3(Mt103Message msg) {
        String chargeCode = msg.getFieldValue("71A");
        if (chargeCode == null) return;

        // BUG: inverted logic - should check if 71A IS "BEN" and 71F IS present
        if (!"BEN".equals(chargeCode.trim()) && msg.hasField("71F")) {
            msg.addError(":71F:", "C3_VIOLATION", "Field :71F: not allowed when :71A: is BEN");
        }
    }

    /**
     * C4: If :71A: is OUR, :71G: may be present; :71F: may also be present.
     * This is a permissive rule, no validation errors to report for OUR.
     */
    private static void validateC4(Mt103Message msg) {
        // OUR is the most permissive - both 71F and 71G are allowed
        // No validation needed
    }

    /**
     * C5: If :71A: is SHA, then :71G: must not be present.
     *
     * BUG: Not implemented
     */
    private static void validateC5(Mt103Message msg) {
        // TODO: implement C5 rule
    }

    /**
     * C6: :72: sender-to-receiver info lines must start with / for first line
     * and // for continuation lines. Code words max 8 chars.
     *
     * BUG: Not implemented
     */
    private static void validateC6(Mt103Message msg) {
        // TODO: implement C6 rule
    }
}
