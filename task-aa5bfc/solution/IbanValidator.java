package swift;


public class IbanValidator {

    public static boolean isValid(String iban) {
        if (iban == null) return false;
        iban = iban.replaceAll("\\s+", "").toUpperCase();

        if (iban.length() < 5) return false;

        if (!iban.substring(0, 2).matches("[A-Z]{2}")) return false;
        if (!iban.substring(2, 4).matches("\\d{2}")) return false;

        // Move first 4 chars to end
        String rearranged = iban.substring(4) + iban.substring(0, 4);

        // Convert to number string
        StringBuilder numStr = new StringBuilder();
        for (char c : rearranged.toCharArray()) {
            if (Character.isDigit(c)) {
                numStr.append(c);
            } else if (Character.isLetter(c)) {
                // FIX: Use 'A' (uppercase) since we already uppercased the input
                int val = c - 'A' + 10;
                numStr.append(val);
            } else {
                return false;
            }
        }

        return mod97(numStr.toString()) == 1;
    }

    private static int mod97(String number) {
        long remainder = 0;
        for (int i = 0; i < number.length(); i++) {
            int digit = number.charAt(i) - '0';
            remainder = (remainder * 10 + digit) % 97;
        }
        return (int) remainder;
    }
}
