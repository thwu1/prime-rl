package swift;

import java.io.FileWriter;
import java.io.IOException;
import java.util.List;


public class Pacs008Mapper {

    private static final String NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08";

    public static void mapToXml(List<Mt103Message> messages, String outputPath) throws IOException {
        StringBuilder xml = new StringBuilder();
        xml.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
        xml.append("<Document xmlns=\"").append(NAMESPACE).append("\">\n");
        xml.append("  <FIToFICstmrCdtTrf>\n");

        int validCount = 0;
        for (Mt103Message m : messages) {
            if (m.valid) validCount++;
        }

        xml.append("    <GrpHdr>\n");
        xml.append("      <MsgId>BATCH-CONVERT-001</MsgId>\n");
        xml.append("      <CreDtTm>2023-01-15T00:00:00</CreDtTm>\n");
        xml.append("      <NbOfTxs>").append(validCount).append("</NbOfTxs>\n");
        xml.append("      <SttlmInf>\n");
        xml.append("        <SttlmMtd>INGA</SttlmMtd>\n");
        xml.append("      </SttlmInf>\n");
        xml.append("    </GrpHdr>\n");

        for (Mt103Message msg : messages) {
            if (!msg.valid) continue;
            mapTransaction(xml, msg);
        }

        xml.append("  </FIToFICstmrCdtTrf>\n");
        xml.append("</Document>\n");

        try (FileWriter fw = new FileWriter(outputPath)) {
            fw.write(xml.toString());
        }
    }

    private static void mapTransaction(StringBuilder xml, Mt103Message msg) {
        xml.append("    <CdtTrfTxInf>\n");

        // Payment ID - use reference for both EndToEndId and TxId
        xml.append("      <PmtId>\n");
        xml.append("        <EndToEndId>").append(escapeXml(msg.reference)).append("</EndToEndId>\n");
        xml.append("        <TxId>").append(escapeXml(msg.reference)).append("</TxId>\n");
        xml.append("      </PmtId>\n");

        // Settlement Amount - format as proper decimal
        String formattedAmount = formatAmount(msg.settlementAmount);
        xml.append("      <IntrBkSttlmAmt Ccy=\"").append(escapeXml(msg.settlementCurrency)).append("\">")
           .append(formattedAmount).append("</IntrBkSttlmAmt>\n");

        // Settlement Date
        String field32A = msg.getFieldValue("32A");
        if (field32A != null && field32A.length() >= 6) {
            String dateStr = field32A.substring(0, 6);
            String isoDate = convertDate(dateStr);
            xml.append("      <IntrBkSttlmDt>").append(isoDate).append("</IntrBkSttlmDt>\n");
        }

        // Charge Bearer - map MT codes to ISO 20022
        String chargeBearer = msg.getFieldValue("71A");
        if (chargeBearer != null) {
            xml.append("      <ChrgBr>").append(mapChargeBearer(chargeBearer.trim())).append("</ChrgBr>\n");
        }

        // Instructing Agent (sender)
        xml.append("      <InstgAgt>\n");
        xml.append("        <FinInstnId>\n");
        xml.append("          <BICFI>").append(escapeXml(msg.senderBic)).append("</BICFI>\n");
        xml.append("        </FinInstnId>\n");
        xml.append("      </InstgAgt>\n");

        // Instructed Agent (receiver)
        xml.append("      <InstdAgt>\n");
        xml.append("        <FinInstnId>\n");
        xml.append("          <BICFI>").append(escapeXml(msg.receiverBic)).append("</BICFI>\n");
        xml.append("        </FinInstnId>\n");
        xml.append("      </InstdAgt>\n");

        // Debtor (ordering customer)
        String debtorName = extractPartyName(msg, "50");
        xml.append("      <Dbtr>\n");
        xml.append("        <Nm>").append(escapeXml(debtorName)).append("</Nm>\n");
        xml.append("      </Dbtr>\n");

        // Creditor (beneficiary)
        String creditorName = extractPartyName(msg, "59");
        xml.append("      <Cdtr>\n");
        xml.append("        <Nm>").append(escapeXml(creditorName)).append("</Nm>\n");
        xml.append("      </Cdtr>\n");

        xml.append("    </CdtTrfTxInf>\n");
    }

    /**
     * Convert YYMMDD to YYYY-MM-DD.
     * YY < 50 -> 20xx, YY >= 50 -> 19xx (SWIFT convention).
     */
    private static String convertDate(String yymmdd) {
        if (yymmdd.length() < 6) return "2000-01-01";
        int yy = Integer.parseInt(yymmdd.substring(0, 2));
        String mm = yymmdd.substring(2, 4);
        String dd = yymmdd.substring(4, 6);
        String century = (yy < 50) ? "20" : "19";
        return century + String.format("%02d", yy) + "-" + mm + "-" + dd;
    }

    /**
     * Map MT charge bearer codes to ISO 20022 codes.
     */
    private static String mapChargeBearer(String mtCode) {
        switch (mtCode) {
            case "SHA": return "SHAR";
            case "BEN": return "DEBT";
            case "OUR": return "CRED";
            default: return mtCode;
        }
    }

    /**
     * Format amount as fixed-point decimal with 2 decimal places.
     */
    private static String formatAmount(String rawAmount) {
        try {
            double d = Double.parseDouble(rawAmount);
            return String.format("%.2f", d);
        } catch (NumberFormatException e) {
            return "0.00";
        }
    }

    /**
     * Extract party name from :50x: or :59x: fields.
     * :50K:/:59: - account on first line (/xxx), name on second line.
     * :50F:/:59F: - name on line starting with "1/".
     * :50A:/:59A: - BIC on last line.
     */
    private static String extractPartyName(Mt103Message msg, String baseTag) {
        String value = null;
        String matchedSuffix = "";
        for (String suffix : new String[]{"F", "K", "A", ""}) {
            String tag = baseTag + suffix;
            if (msg.hasField(tag)) {
                value = msg.getFieldValue(tag);
                matchedSuffix = suffix;
                break;
            }
        }
        if (value == null) return "UNKNOWN";

        String[] lines = value.split("\\n");

        if ("F".equals(matchedSuffix)) {
            // Structured format: line starting with "1/" is the name
            for (String line : lines) {
                if (line.startsWith("1/")) {
                    return line.substring(2).trim();
                }
            }
            return lines.length > 1 ? lines[1].trim() : "UNKNOWN";
        } else if ("A".equals(matchedSuffix)) {
            // :50A: / :59A: - BIC on last line
            return lines[lines.length - 1].trim();
        } else {
            // :50K: / :59: - account on first line (starts with /), name on second line
            if (lines.length > 1 && lines[0].startsWith("/")) {
                return lines[1].trim();
            }
            return lines[0].trim();
        }
    }

    private static String escapeXml(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&apos;");
    }
}
