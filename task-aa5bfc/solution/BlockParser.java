package swift;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;


public class BlockParser {

    public static List<String> splitBatch(String batchContent) {
        List<String> messages = new ArrayList<>();
        String[] parts = batchContent.split("\\n\\$\\n");
        for (String part : parts) {
            String trimmed = part.trim();
            if (!trimmed.isEmpty()) {
                messages.add(trimmed);
            }
        }
        return messages;
    }

    public static Mt103Message parse(String fin) {
        Mt103Message msg = new Mt103Message();
        if (fin == null || fin.isEmpty()) {
            msg.addError("STRUCTURE", "PARSE_ERROR", "Empty message");
            return msg;
        }

        String working = fin;

        // FIX: Handle ACK-prepended messages.
        // If the message starts with {1:F21...} (service ID 21 = ACK/NAK),
        // skip to the second {1:F01...} block.
        Pattern ackPattern = Pattern.compile("^\\{1:F21");
        if (ackPattern.matcher(working).find()) {
            // Find the second occurrence of {1:
            int secondBlock1 = working.indexOf("{1:", working.indexOf("{1:") + 1);
            if (secondBlock1 >= 0) {
                working = working.substring(secondBlock1);
            }
        }

        // Extract block 1
        Pattern b1Pattern = Pattern.compile("\\{1:([^}]+)\\}");
        Matcher b1m = b1Pattern.matcher(working);
        if (b1m.find()) {
            msg.block1 = b1m.group(1);
            // Format: F01BANKBEBBAXXX0000000000
            // Sender BIC8 starts at position 3, length 8
            if (msg.block1.length() >= 11) {
                // Extract BIC8 (positions 3-10, which is 8 chars for institution+country+location)
                msg.senderBic = msg.block1.substring(3, 11);
            }
        }

        // Extract block 2
        Pattern b2Pattern = Pattern.compile("\\{2:([^}]+)\\}");
        Matcher b2m = b2Pattern.matcher(working);
        if (b2m.find()) {
            msg.block2 = b2m.group(1);
            if (msg.block2.startsWith("I")) {
                // Input: I103BANKDEFFXXXXN -> receiver BIC at position 4, 8 chars for BIC8
                if (msg.block2.length() >= 12) {
                    msg.receiverBic = msg.block2.substring(4, 12);
                }
            } else if (msg.block2.startsWith("O")) {
                // Output: O103HHMM YYMMDD SENDER_LT_12 ...
                // Format: O1030803051028AAPBESMMAXXX54237368560510280803N
                // The sender BIC (from MIR) starts at position 14 (after O + 103 + HHMM + YYMMDD), 12 chars for LT
                // But for receiver BIC in output messages, we need the original sender from MIR
                // MIR = YYMMDD + sender LT address (12 chars)
                // Position: O(1) + type(3) + inputTime(4) + MIR_date(6) + sender_LT(12)
                // = position 14 through 25
                if (msg.block2.length() >= 26) {
                    String senderLt = msg.block2.substring(14, 26);
                    // Extract BIC8 from LT address (first 8 chars)
                    msg.receiverBic = senderLt.substring(0, 8);
                }
            }
        }

        // Extract block 3 - handle nested braces
        int b3Start = working.indexOf("{3:");
        if (b3Start >= 0) {
            int depth = 0;
            int b3End = -1;
            for (int i = b3Start; i < working.length(); i++) {
                if (working.charAt(i) == '{') depth++;
                else if (working.charAt(i) == '}') {
                    depth--;
                    if (depth == 0) {
                        b3End = i;
                        break;
                    }
                }
            }
            if (b3End >= 0) {
                msg.block3 = working.substring(b3Start, b3End + 1);
            }
        }

        // Extract block 4
        int b4Start = working.indexOf("{4:");
        if (b4Start >= 0) {
            int b4End = working.indexOf("-}", b4Start);
            if (b4End >= 0) {
                msg.block4Raw = working.substring(b4Start + 3, b4End);
                parseBlock4Fields(msg);
            }
        }

        // Extract block 5
        int b5Start = working.indexOf("{5:");
        if (b5Start >= 0) {
            int depth = 0;
            int b5End = -1;
            for (int i = b5Start; i < working.length(); i++) {
                if (working.charAt(i) == '{') depth++;
                else if (working.charAt(i) == '}') {
                    depth--;
                    if (depth == 0) {
                        b5End = i;
                        break;
                    }
                }
            }
            if (b5End >= 0) {
                msg.block5 = working.substring(b5Start, b5End + 1);
            }
        }

        if (msg.hasField("20")) {
            msg.reference = msg.getFieldValue("20");
        }

        return msg;
    }

    /**
     * FIX: Properly handle multi-line fields.
     * Lines that don't start with :TAG: are continuation lines of the previous field.
     */
    private static void parseBlock4Fields(Mt103Message msg) {
        String content = msg.block4Raw;
        if (content == null || content.isEmpty()) return;

        String[] lines = content.split("\\r?\\n");
        Pattern tagPattern = Pattern.compile("^:(\\d{2}[A-Z]?):(.*)", Pattern.DOTALL);

        String currentTag = null;
        StringBuilder currentValue = new StringBuilder();

        for (String line : lines) {
            if (line.trim().isEmpty()) continue;

            Matcher m = tagPattern.matcher(line);
            if (m.matches()) {
                // Save previous field if any
                if (currentTag != null) {
                    msg.addField(currentTag, currentValue.toString());
                }
                currentTag = m.group(1);
                currentValue = new StringBuilder(m.group(2));
            } else if (currentTag != null) {
                // Continuation line
                currentValue.append("\n").append(line);
            }
        }

        // Save last field
        if (currentTag != null) {
            msg.addField(currentTag, currentValue.toString());
        }
    }

    public static boolean block3HasSubTag(String block3, String subTag, String value) {
        if (block3 == null || block3.isEmpty()) return false;
        String search = "{" + subTag + ":" + value + "}";
        return block3.contains(search);
    }

    public static String getBlock3SubTagValue(String block3, String subTag) {
        if (block3 == null || block3.isEmpty()) return null;
        Pattern p = Pattern.compile("\\{" + subTag + ":([^}]*)\\}");
        Matcher m = p.matcher(block3);
        if (m.find()) {
            return m.group(1);
        }
        return null;
    }
}
