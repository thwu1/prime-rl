package swift;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;


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
        "ALL", "BAM", "MKD", "RSD", "RON", "BGN", "HRK", "ISK",
        "XOF", "XAF", "XCD", "XPF", "XDR", "XAU", "XAG",
        "XPT", "XPD", "XBA", "XBB", "XBC", "XBD", "XTS", "XXX",
        "SDG", "SSP", "SOS", "DJF", "ERN", "GMD", "GNF", "LRD",
        "MWK", "MZN", "NAD", "SLL", "STN", "SZL", "ZMW", "ZWL",
        "BIF", "CDF", "CVE", "KMF", "LSL", "BWP", "AOA"
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

        if (mm < 1 || mm > 12) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid month in :32A: date");
        }
        if (dd < 1 || dd > 31) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid day in :32A: date");
        }

        if (!currency.matches("[A-Z]{3}")) {
            msg.addError(":32A:", "FORMAT_ERROR", "Invalid currency format in :32A:");
        } else if (!ISO_4217_CURRENCIES.contains(currency)) {
            msg.addError(":32A:", "INVALID_CURRENCY", "Unknown ISO 4217 currency: " + currency);
        }

        msg.settlementCurrency = currency;

        try {
            String normalizedAmount;
            if (amountStr.endsWith(",")) {
                normalizedAmount = amountStr.substring(0, amountStr.length() - 1);
            } else {
                normalizedAmount = amountStr.replace(",", ".");
            }
            if (normalizedAmount.isEmpty()) {
                msg.addError(":32A:", "FORMAT_ERROR", "Empty amount in :32A:");
                return;
            }
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
            if (parts.length > 0 && parts[0].startsWith("/")) {
                checkIban(msg, ":50A:", parts[0].substring(1));
            }
            String bic;
            if (parts.length > 1 && parts[0].startsWith("/")) {
                bic = parts[parts.length - 1].trim();
            } else {
                bic = parts[0].trim();
            }
            validateBic(msg, ":50A:", bic);
        }

        if (has50F) {
            String val = msg.getFieldValue("50F");
            String[] parts = val.split("\\n");
            if (parts.length > 0 && parts[0].startsWith("/")) {
                checkIban(msg, ":50F:", parts[0].substring(1));
            }
        }

        if (has50K) {
            String val = msg.getFieldValue("50K");
            String[] parts = val.split("\\n");
            if (parts.length > 0 && parts[0].startsWith("/")) {
                checkIban(msg, ":50K:", parts[0].substring(1));
            }
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

        // Check IBAN for whichever variant is present
        String tag = has59 ? "59" : (has59A ? "59A" : (has59F ? "59F" : null));
        if (tag != null) {
            String val = msg.getFieldValue(tag);
            if (val != null) {
                String[] parts = val.split("\\n");
                if (parts.length > 0 && parts[0].startsWith("/")) {
                    checkIban(msg, ":" + tag + ":", parts[0].substring(1));
                }
            }
        }

        // Validate BIC in :59A:
        if (has59A) {
            String val = msg.getFieldValue("59A");
            String[] parts = val.split("\\n");
            String bic;
            if (parts.length > 1 && parts[0].startsWith("/")) {
                bic = parts[parts.length - 1].trim();
            } else {
                bic = parts[0].trim();
            }
            validateBic(msg, ":59A:", bic);
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
     * BIC validation per ISO 9362: 4 alpha + 2 alpha + 2 alphanum + optional 3 alphanum.
     */
    public static void validateBic(Mt103Message msg, String fieldTag, String bic) {
        if (bic == null || bic.isEmpty()) return;
        bic = bic.trim();
        if (!bic.matches("[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?")) {
            msg.addError(fieldTag, "INVALID_BIC", "Invalid BIC format: " + bic);
        }
    }

    /**
     * Check IBAN validity for accounts matching the IBAN pattern.
     */
    private static void checkIban(Mt103Message msg, String fieldTag, String account) {
        if (account != null && account.matches("[A-Z]{2}\\d{2}.*")) {
            if (!IbanValidator.isValid(account)) {
                msg.addError(fieldTag, "INVALID_IBAN", "Invalid IBAN: " + account);
            }
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
