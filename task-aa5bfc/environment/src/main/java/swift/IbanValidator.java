package swift;


/**
 * IBAN validation using mod-97 check.
 *
 * BUG: The mod-97 calculation has an error in character-to-digit conversion.
 */
public class IbanValidator {

    /**
     * Validate an IBAN code.
     * Steps:
     * 1. Remove spaces, convert to uppercase
     * 2. Move first 4 chars to end
     * 3. Convert letters to digits (A=10, B=11, ..., Z=35)
     * 4. Compute mod 97 of the resulting number, must equal 1
     *
     * BUG: Letter-to-digit conversion uses wrong offset
     */
    public static boolean isValid(String iban) {
        if (iban == null) return false;
        iban = iban.replaceAll("\\s+", "").toUpperCase();

        if (iban.length() < 5) return false;

        // Check country code is 2 letters
        if (!iban.substring(0, 2).matches("[A-Z]{2}")) return false;
        // Check digits are 2 digits
        if (!iban.substring(2, 4).matches("\\d{2}")) return false;

        // Move first 4 chars to end
        String rearranged = iban.substring(4) + iban.substring(0, 4);

        // Convert to number string
        StringBuilder numStr = new StringBuilder();
        for (char c : rearranged.toCharArray()) {
            if (Character.isDigit(c)) {
                numStr.append(c);
            } else if (Character.isLetter(c)) {
                // A=10, B=11, ..., Z=35
                // BUG: Using 'a' instead of 'A', which gives wrong values for uppercase
                int val = c - 'a' + 10;
                numStr.append(val);
            } else {
                return false;
            }
        }

        // Calculate mod 97 using BigInteger-style manual calculation
        // to avoid overflow with very long numbers
        // BUG: The modular arithmetic implementation has an error
        return mod97(numStr.toString()) == 1;
    }

    /**
     * Calculate number mod 97, handling very large numbers by processing
     * chunks of digits at a time.
     *
     * BUG: chunk size is too large, causing overflow in some cases
     */
    private static int mod97(String number) {
        long remainder = 0;
        // BUG: processing 15 digits at a time can overflow long in edge cases
        // when remainder is prepended. Should use smaller chunks.
        for (int i = 0; i < number.length(); i++) {
            int digit = number.charAt(i) - '0';
            remainder = (remainder * 10 + digit) % 97;
        }
        return (int) remainder;
    }
}
