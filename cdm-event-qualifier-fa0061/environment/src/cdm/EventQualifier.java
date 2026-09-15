package cdm;

import java.nio.file.Files;
import java.nio.file.Path;

/**
 * CDM BusinessEvent Qualifier.
 *
 * Reads a CDM BusinessEvent JSON file and prints the event qualifier to stdout.
 * Usage: java cdm.EventQualifier <path-to-event.json>
 */
public class EventQualifier {

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("Usage: java cdm.EventQualifier <event.json>");
            System.exit(1);
        }
        String json = Files.readString(Path.of(args[0]));
        String qualifier = qualify(json);
        System.out.println(qualifier);
    }

    public static String qualify(String json) {
        // TODO: Implement CDM BusinessEvent qualification logic.
        // Parse the JSON, analyze the event structure, and return the qualifier.
        throw new UnsupportedOperationException("Qualification logic not implemented");
    }
}
