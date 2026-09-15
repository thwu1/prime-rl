package swift;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;


/**
 * Validates individual MT103 fields against their format specifications.
 */
public class FieldValidator {

    private static final Set<String> ISO_4217_CURRENCIES = new HashSet<>(Arrays.asList(
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
        "SEK", "NOK", "DKK", "SGD", "HKD", "ZAR", "MXN", "BRL",
        "INR", "CNY", "KRW", "THB", "MYR", "PHP", "IDR", "TWD",
        "PLN", "CZK", "HUF", "RUB", "TRY", "ILS", "AED", "SAR",
        "KWD", "BHD", "OMR", "QAR", "JOD", "EGP", "NGN", "KES",
        "GHS", "TZS", "UGX", "RWF", "ETB", "MAD", "TND", "LYD",
        "CLP", "COP", "PEN", "ARS", "UYU", "VES", "BOB", "PYG",
        "DOP", "GTQ", "HNL", "NIO", "CRC", "PAB", "TTD", "JMD",
        "BBD", "BSD", "BZD", "GYD", "SRD", "FJD", "PGK", "WST",
        "TOP", "VUV", "SBD", "SCR", "MUR", "MVR", "LKR", "NPR",
        "PKR", "BDT", "MMK", "LAK", "KHR", "VND", "MNT", "KZT",
        "UZS", "TMT", "AZN", "GEL", "AMD", "MDL", "UAH", "BYN",
        "ALL", "BAM", "MKD", "RSD", "RON", "BGN", "HRK", "ISK"
        // BUG: XOF, XAF, XCD, XPF and other X-currencies are missing
    ));

    public static void validateField20(Mt103Message msg) {
        String value = msg.getFieldValue("20");
        if (value == null) {
            msg.addError(":20:", "MISSING_FIELD", "Mandatory field :20: is missing");
            return;
        }
        if (value.length() > 16) {
            msg.addError(":20:", "FORMAT_ERROR", "Field :20: exceeds 16 characters");
        }
        if (value.startsWith("/") || value.endsWith("/")) {
            msg.addError(":20:", "FORMAT_ERROR", "Field :20: must not start or end with /");
        }
        if (value.contains("//")) {
            msg.addError(":20:", "FORMAT_ERROR", "Field :20: must not contain //");
        }
    }

    public static void validateField23B(Mt103Message msg) {
        String value = msg.getFieldValue("23B");
        if (value == null) {
            msg.addError(":23B:", "MISSING_FIELD", "Mandatory field :23B: is missing");
            return;
        }
        Set<String> validCodes = new HashSet<>(Arrays.asList("CRED", "CRTS", "SPAY", "SPRI", "SSTD"));
        if (!validCodes.contains(value.trim())) {
            msg.addError(":23B:", "FORMAT_ERROR", "Invalid bank operation code: " + value);
        }
    }

    /**
     * Validate field :32A: Value Date/Currency/Amount
     * Format: 6!n3!a15d
     *
     * BUG: month validation allows month 0 and 13
     * BUG: day validation allows day 0
     * BUG: amount parsing fails on trailing comma
     * BUG: missing XOF and other currencies
     */
    public static void validateField32A(Mt103Message msg) {
        String value = msg.getFieldValue("32A");
        if (value == null) {
            msg.addError(":32A:", "MISSING_FIELD", "Mandatory field :32A: is missing");
            return;
        }

        if (value.length() < 9) {
            msg.addError(":32A:", "FORMAT_ERROR", "Field :32A: too short");
            return;
        }

        String dateStr = value.substring(0, 6);
        String currency = value.substring(6, 9);
        String amountStr = value.substring(9);

        if (!dateStr.matches("\\d{6}")) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid date format in :32A:");
            return;
        }

        int mm = Integer.parseInt(dateStr.substring(2, 4));
        int dd = Integer.parseInt(dateStr.substring(4, 6));

        // BUG: allows month 0 and month 13
        if (mm < 0 || mm > 13) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid month in :32A: date");
        }
        // BUG: allows day 0
        if (dd < 0 || dd > 31) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid day in :32A: date");
        }

        if (!currency.matches("[A-Z]{3}")) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid currency format in :32A:");
        } else if (!ISO_4217_CURRENCIES.contains(currency)) {
            msg.addError(":32A:", "INVALID_CURRENCY", "Unknown ISO 4217 currency: " + currency);
        }

        msg.settlementCurrency = currency;
        try {
            // BUG: Doesn't handle trailing comma (e.g., "100000," = 100000.00)
            String normalizedAmount = amountStr.replace(",", ".");
            double amount = Double.parseDouble(normalizedAmount);
            msg.settlementAmount = String.valueOf(amount);
        } catch (NumberFormatException e) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid amount format in :32A:");
        }
    }

    public static void validateField50(Mt103Message msg) {
        boolean has50A = msg.hasField("50A");
        boolean has50F = msg.hasField("50F");
        boolean has50K = msg.hasField("50K");

        int count = (has50A ? 1 : 0) + (has50F ? 1 : 0) + (has50K ? 1 : 0);

        if (count == 0) {
            msg.addError(":50a:", "MISSING_FIELD", "One of :50A:, :50F:, or :50K: is mandatory");
        } else if (count > 1) {
            msg.addError(":50a:", "MULTIPLE_OPTIONS", "Only one of :50A:, :50F:, :50K: allowed");
        }

        if (has50A) {
            String val = msg.getFieldValue("50A");
            String[] parts = val.split("\\n");
            String bic;
            if (parts.length > 1 && parts[0].startsWith("/")) {
                bic = parts[parts.length - 1].trim();
            } else {
                bic = parts[0].trim();
            }
            validateBic(msg, ":50A:", bic);
        }
    }

    public static void validateField59(Mt103Message msg) {
        boolean has59 = msg.hasField("59");
        boolean has59A = msg.hasField("59A");
        boolean has59F = msg.hasField("59F");

        int count = (has59 ? 1 : 0) + (has59A ? 1 : 0) + (has59F ? 1 : 0);

        if (count == 0) {
            msg.addError(":59a:", "MISSING_FIELD", "One of :59:, :59A:, or :59F: is mandatory");
        } else if (count > 1) {
            msg.addError(":59a:", "MULTIPLE_OPTIONS", "Only one of :59:, :59A:, :59F: allowed");
        }
    }

    public static void validateField71A(Mt103Message msg) {
        String value = msg.getFieldValue("71A");
        if (value == null) {
            msg.addError(":71A:", "MISSING_FIELD", "Mandatory field :71A: is missing");
            return;
        }
        Set<String> validCodes = new HashSet<>(Arrays.asList("BEN", "OUR", "SHA"));
        if (!validCodes.contains(value.trim())) {
            msg.addError(":71A:", "FORMAT_ERROR", "Invalid charges code: " + value);
        }
    }

    /**
     * BUG: allows digits in institution code (first 4 chars must be alpha only)
     */
    public static void validateBic(Mt103Message msg, String fieldTag, String bic) {
        if (bic == null || bic.isEmpty()) return;
        bic = bic.trim();
        // BUG: regex allows digits in institution code
        if (!bic.matches("[A-Z0-9]{4}[A-Z0-9]{2}[A-Z0-9]{2}([A-Z0-9]{3})?")) {
            msg.addError(fieldTag, "INVALID_BIC", "Invalid BIC format: " + bic);
        }
    }

    public static void validateAll(Mt103Message msg) {
        validateField20(msg);
        validateField23B(msg);
        validateField32A(msg);
        validateField50(msg);
        validateField59(msg);
        validateField71A(msg);
    }
}
