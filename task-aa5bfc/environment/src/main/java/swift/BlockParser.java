package swift;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;


/**
 * Parses raw FIN text into Mt103Message objects.
 * Handles the 5-block SWIFT message structure.
 */
public class BlockParser {

    /**
     * Split a batch file into individual message strings.
     * Messages are separated by '$' on its own line.
     */
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

    /**
     * Parse a single FIN message string into an Mt103Message.
     * BUG: Does not handle ACK-prepended messages correctly.
     * BUG: Block 3 sub-tag extraction is broken.
     * BUG: Block 4 multi-line field parsing is incorrect.
     * BUG: Sender/receiver BIC extraction has off-by-one errors.
     */
    public static Mt103Message parse(String fin) {
        Mt103Message msg = new Mt103Message();
        if (fin == null || fin.isEmpty()) {
            msg.addError("STRUCTURE", "PARSE_ERROR", "Empty message");
            return msg;
        }

        // NOTE: This parser does NOT handle ACK-prepended messages.
        // If a message starts with {1:F21...} (service ID 21 = ACK/NAK),
        // we should skip to the second {1:F01...} block.
        // Currently we just parse from the beginning, which will produce wrong results.

        String working = fin;

        // Extract block 1
        Pattern b1Pattern = Pattern.compile("\\{1:([^}]+)\\}");
        Matcher b1m = b1Pattern.matcher(working);
        if (b1m.find()) {
            msg.block1 = b1m.group(1);
            // Extract sender BIC from block 1
            // Format: F01BANKBEBBAXXX0000000000
            // BIC starts at position 3, length 8 (BIC8) or 11 (BIC11)
            // BUG: extracting wrong positions
            if (msg.block1.length() >= 11) {
                msg.senderBic = msg.block1.substring(3, 11);
            }
        }

        // Extract block 2
        Pattern b2Pattern = Pattern.compile("\\{2:([^}]+)\\}");
        Matcher b2m = b2Pattern.matcher(working);
        if (b2m.find()) {
            msg.block2 = b2m.group(1);
            // Extract receiver BIC from block 2
            // Input format:  I103BANKDEFFXXXXN  -> receiver BIC at pos 4, length 8 or 12
            // Output format: O1030803051028AAPBESMMAXXX54237368560510280803N -> sender at MIR
            if (msg.block2.startsWith("I")) {
                // Input message: receiver BIC starts at position 4
                // BUG: extracting 12 chars instead of correct BIC8
                if (msg.block2.length() >= 16) {
                    msg.receiverBic = msg.block2.substring(4, 16);
                }
            } else if (msg.block2.startsWith("O")) {
                // Output message: need to extract from MIR
                // Format: O103HHMM YYMMDD SENDER_BIC_12 ...
                // BUG: not handling output header at all, just leaving empty
                msg.receiverBic = "";
            }
        }

        // Extract block 3
        Pattern b3Pattern = Pattern.compile("\\{3:(\\{[^}]*\\})+\\}");
        Matcher b3m = b3Pattern.matcher(working);
        if (b3m.find()) {
            msg.block3 = b3m.group(0);
        }

        // Extract block 4
        // Block 4 starts with {4: and ends with -}
        // BUG: This regex doesn't handle multi-line content properly
        int b4Start = working.indexOf("{4:");
        if (b4Start >= 0) {
            // Find the closing -}
            // BUG: searching for -} but not accounting for potential -} inside field values
            int b4End = working.indexOf("-}", b4Start);
            if (b4End >= 0) {
                msg.block4Raw = working.substring(b4Start + 3, b4End);
                parseBlock4Fields(msg);
            }
        }

        // Extract block 5
        Pattern b5Pattern = Pattern.compile("\\{5:(\\{[^}]*\\})+\\}");
        Matcher b5m = b5Pattern.matcher(working);
        if (b5m.find()) {
            msg.block5 = b5m.group(0);
        }

        // Set reference
        if (msg.hasField("20")) {
            msg.reference = msg.getFieldValue("20");
        }

        return msg;
    }

    /**
     * Parse block 4 content into individual fields.
     * Fields start with :TAG: pattern on a new line.
     * Multi-line fields: subsequent lines that don't match :TAG: are continuations.
     *
     * BUG: This implementation doesn't handle multi-line fields at all.
     * It splits on newlines and only takes single-line values.
     */
    private static void parseBlock4Fields(Mt103Message msg) {
        String content = msg.block4Raw;
        if (content == null || content.isEmpty()) return;

        String[] lines = content.split("\\r?\\n");
        Pattern tagPattern = Pattern.compile("^:(\\d{2}[A-Z]?):(.*)", Pattern.DOTALL);

        // BUG: Only takes the first line of each field, ignoring continuation lines
        for (String line : lines) {
            line = line.trim();
            if (line.isEmpty()) continue;

            Matcher m = tagPattern.matcher(line);
            if (m.matches()) {
                String tag = m.group(1);
                String value = m.group(2);
                // BUG: just takes this single line, doesn't append continuation lines
                msg.addField(tag, value);
            }
            // BUG: continuation lines (that don't start with :TAG:) are silently dropped
        }
    }

    /**
     * Check if block 3 contains a specific sub-tag value.
     * Block 3 format: {3:{113:NOMF}{108:xxx}{119:STP}}
     *
     * BUG: This method uses indexOf which doesn't properly parse sub-tags.
     * It could match partial values or values in wrong sub-tags.
     */
    public static boolean block3HasSubTag(String block3, String subTag, String value) {
        if (block3 == null || block3.isEmpty()) return false;
        // BUG: just does a simple string contains check, not proper sub-tag parsing
        return block3.contains(subTag + ":" + value);
    }

    /**
     * Extract a sub-tag value from block 3.
     */
    public static String getBlock3SubTagValue(String block3, String subTag) {
        if (block3 == null || block3.isEmpty()) return null;
        // BUG: naive regex that may not work with all block 3 formats
        Pattern p = Pattern.compile("\\{" + subTag + ":([^}]*)\\}");
        Matcher m = p.matcher(block3);
        if (m.find()) {
            return m.group(1);
        }
        return null;
    }
}
