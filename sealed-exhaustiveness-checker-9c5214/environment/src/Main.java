import java.io.*;
import java.util.*;


/**
 * Entry point and input parser for the sealed-type exhaustiveness checker.
 *
 * Usage:  java Main <input_file>
 *
 * Input file format
 * -----------------
 * Two sections headed by TYPES and SWITCHES.
 *
 * Type definitions (one per line):
 *   sealed   <name> <sub1> <sub2> ...
 *   record   <name> <type>:<compName> ... [parent:<sealedParent>]
 *   enum     <name> <const1> <const2> ...
 *   enum_body <name> <const1> <const2> ...    (constants with class bodies)
 *   final    <name> [parent:<sealedParent>]
 *   class    <name>
 *
 * Switch definitions:
 *   switch <id> <selectorType>
 *     type <TypeName>
 *     record <TypeName>(<compPattern1>,<compPattern2>,...)
 *        where compPattern = type:<T> | any
 *     enum <EnumType>.<CONSTANT>
 *     null
 *     default
 *     guarded_type <TypeName>
 *     guarded_enum <EnumType>.<CONSTANT>
 *   end
 *
 * Lines starting with '#' and blank lines are ignored.
 */
public class Main {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java Main <input_file>");
            System.exit(1);
        }
        TypeRegistry registry = new TypeRegistry();
        List<SwitchDef> switches = new ArrayList<>();
        parse(args[0], registry, switches);

        ExhaustivenessChecker checker = new ExhaustivenessChecker(registry);
        for (SwitchDef sw : switches) {
            AnalysisResult result = checker.analyze(sw);
            System.out.println(result.format(sw.id));
        }
    }

    // ---------------------------------------------------------------
    // Parsing
    // ---------------------------------------------------------------

    static void parse(String filename, TypeRegistry registry,
                      List<SwitchDef> switches) throws Exception {
        BufferedReader reader = new BufferedReader(new FileReader(filename));
        String section = "types";
        SwitchDef currentSwitch = null;
        String line;

        while ((line = reader.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;

            if (line.equals("TYPES"))    { section = "types";    continue; }
            if (line.equals("SWITCHES")) { section = "switches"; continue; }

            if ("types".equals(section)) {
                parseType(line, registry);
            } else {
                if (line.startsWith("switch ")) {
                    String[] parts = line.substring(7).trim().split("\\s+");
                    currentSwitch = new SwitchDef(parts[0], parts[1]);
                    switches.add(currentSwitch);
                } else if (line.equals("end")) {
                    currentSwitch = null;
                } else if (currentSwitch != null) {
                    currentSwitch.cases.add(parseCase(line));
                }
            }
        }
        reader.close();
    }

    static void parseType(String line, TypeRegistry registry) {
        String[] tokens = line.split("\\s+");
        String kind = tokens[0];
        String name = tokens[1];
        TypeDef def = new TypeDef(name, kind);

        switch (kind) {
            case "sealed":
                for (int i = 2; i < tokens.length; i++)
                    def.permits.add(tokens[i]);
                break;
            case "record":
                for (int i = 2; i < tokens.length; i++) {
                    String tok = tokens[i];
                    if (tok.startsWith("parent:")) {
                        def.sealedParent = tok.substring(7);
                    } else {
                        String[] comp = tok.split(":");
                        def.components.add(new String[]{comp[0], comp[1]});
                    }
                }
                break;
            case "enum":
                for (int i = 2; i < tokens.length; i++)
                    def.enumConstants.add(tokens[i]);
                break;
            case "enum_body":
                for (int i = 2; i < tokens.length; i++) {
                    def.enumConstants.add(tokens[i]);
                    def.permits.add(tokens[i]);
                }
                def.enumBodies = true;
                break;
            case "final":
                for (int i = 2; i < tokens.length; i++) {
                    if (tokens[i].startsWith("parent:"))
                        def.sealedParent = tokens[i].substring(7);
                }
                break;
            case "class":
                break;
        }
        registry.register(def);
    }

    static CasePattern parseCase(String line) {
        line = line.trim();
        if (line.equals("null"))    return new NullPattern();
        if (line.equals("default")) return new DefaultPattern();

        String[] tokens = line.split("\\s+", 2);
        switch (tokens[0]) {
            case "type":
                return new TypePattern(tokens[1].trim());

            case "record": {
                String rest = tokens[1].trim();
                int paren = rest.indexOf('(');
                String typeName = rest.substring(0, paren);
                String comps = rest.substring(paren + 1, rest.length() - 1);
                List<CasePattern> cps = new ArrayList<>();
                for (String comp : comps.split(",")) {
                    comp = comp.trim();
                    if (comp.equals("any"))
                        cps.add(new AnyPattern());
                    else if (comp.startsWith("type:"))
                        cps.add(new TypePattern(comp.substring(5)));
                    else
                        cps.add(new TypePattern(comp));
                }
                return new RecordPattern(typeName, cps);
            }

            case "enum": {
                String[] parts = tokens[1].trim().split("\\.");
                return new EnumConstPattern(parts[0], parts[1]);
            }

            case "guarded_type":
                return new GuardedPattern(new TypePattern(tokens[1].trim()));

            case "guarded_enum": {
                String[] parts = tokens[1].trim().split("\\.");
                return new GuardedPattern(
                        new EnumConstPattern(parts[0], parts[1]));
            }

            default:
                throw new IllegalArgumentException(
                        "Unknown case pattern kind: " + tokens[0]);
        }
    }
}
