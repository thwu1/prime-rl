package swift;

import java.io.FileWriter;
import java.io.IOException;
import java.util.List;


/**
 * Maps validated MT103 messages to ISO 20022 pacs.008.001.08 XML format.
 *
 * BUG: Multiple issues with namespace, element structure, date conversion,
 *      charge code mapping, amount formatting, and party name extraction.
 */
public class Pacs008Mapper {

    // BUG: Wrong namespace URI - missing version suffix .001.08
    private static final String NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pacs.008";

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
        // BUG: xs:dateTime requires seconds - missing :00 at end
        xml.append("      <CreDtTm>2023-01-15T00:00</CreDtTm>\n");
        xml.append("      <NbOfTxs>").append(validCount).append("</NbOfTxs>\n");
        // BUG: SttlmInf element is missing entirely - required by schema
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

        // Payment ID
        xml.append("      <PmtId>\n");
        xml.append("        <EndToEndId>").append(escapeXml(msg.reference)).append("</EndToEndId>\n");
        // BUG: TxId should use the message reference, not a hardcoded value
        xml.append("        <TxId>NOTPROVIDED</TxId>\n");
        xml.append("      </PmtId>\n");

        // Settlement Amount
        // BUG: raw Java double toString can produce scientific notation for large values
        // and inconsistent decimal places. Should format as fixed-point decimal.
        xml.append("      <IntrBkSttlmAmt Ccy=\"").append(escapeXml(msg.settlementCurrency)).append("\">")
           .append(msg.settlementAmount).append("</IntrBkSttlmAmt>\n");

        // Settlement Date - convert YYMMDD from :32A: to YYYY-MM-DD
        String field32A = msg.getFieldValue("32A");
        if (field32A != null && field32A.length() >= 6) {
            String dateStr = field32A.substring(0, 6);
            String isoDate = convertDate(dateStr);
            xml.append("      <IntrBkSttlmDt>").append(isoDate).append("</IntrBkSttlmDt>\n");
        }

        // Charge Bearer
        String chargeBearer = msg.getFieldValue("71A");
        if (chargeBearer != null) {
            // BUG: MT charge codes must be mapped to ISO 20022 codes
            // SHA->SHAR, BEN->DEBT, OUR->CRED
            // This just passes through the raw MT code
            xml.append("      <ChrgBr>").append(escapeXml(chargeBearer.trim())).append("</ChrgBr>\n");
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
     * BUG: Century logic is inverted.
     * Should be: YY < 50 -> 20xx, YY >= 50 -> 19xx
     * But this does: YY >= 50 -> 20xx, YY < 50 -> 19xx
     */
    private static String convertDate(String yymmdd) {
        if (yymmdd.length() < 6) return "2000-01-01";
        int yy = Integer.parseInt(yymmdd.substring(0, 2));
        String mm = yymmdd.substring(2, 4);
        String dd = yymmdd.substring(4, 6);
        // BUG: century logic is backwards
        String century = (yy >= 50) ? "20" : "19";
        return century + String.format("%02d", yy) + "-" + mm + "-" + dd;
    }

    /**
     * Extract party name from :50x: or :59x: fields.
     * BUG: Takes the first line which is usually the account number, not the name.
     * For :50K:/:59: the name is on line 2 (line 1 is /account).
     * For :50F:/:59F: the name is on the line starting with "1/".
     */
    private static String extractPartyName(Mt103Message msg, String baseTag) {
        String value = null;
        for (String suffix : new String[]{"A", "F", "K", ""}) {
            String tag = baseTag + suffix;
            if (msg.hasField(tag)) {
                value = msg.getFieldValue(tag);
                break;
            }
        }
        if (value == null) return "UNKNOWN";

        String[] lines = value.split("\\n");
        // BUG: just takes the first line, which is typically the account number
        return lines[0].trim();
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
