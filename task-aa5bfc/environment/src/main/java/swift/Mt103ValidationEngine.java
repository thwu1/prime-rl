package swift;

import java.io.IOException;
import java.io.FileWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;


/**
 * Main entry point for MT103 validation engine.
 * Usage: java swift.Mt103ValidationEngine <batch_file> <json_output> <xml_output>
 */
public class Mt103ValidationEngine {

    public static void main(String[] args) throws IOException {
        if (args.length < 3) {
            System.err.println("Usage: Mt103ValidationEngine <batch_file> <json_output> <xml_output>");
            System.exit(1);
        }

        String batchFile = args[0];
        String jsonFile = args[1];
        String xmlFile = args[2];

        String content = new String(Files.readAllBytes(Paths.get(batchFile)));
        List<String> rawMessages = BlockParser.splitBatch(content);

        List<Mt103Message> allMessages = new ArrayList<>();
        StringBuilder json = new StringBuilder();
        json.append("[\n");

        for (int i = 0; i < rawMessages.size(); i++) {
            Mt103Message msg = BlockParser.parse(rawMessages.get(i));
            FieldValidator.validateAll(msg);
            CrossFieldValidator.validateAll(msg);
            StpChecker.check(msg);
            allMessages.add(msg);

            if (i > 0) json.append(",\n");
            json.append(msg.toJson(i));
        }

        json.append("\n]");

        // Write JSON report
        try (FileWriter fw = new FileWriter(jsonFile)) {
            fw.write(json.toString());
        }

        // Map valid messages to pacs.008 XML
        Pacs008Mapper.mapToXml(allMessages, xmlFile);

        System.out.println("Processed " + rawMessages.size() + " messages. JSON: " + jsonFile + " XML: " + xmlFile);
    }
}
