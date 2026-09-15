package conjanalysis;

import java.io.*;

/**
 * Entry point for the conjunction analysis tool.
 *
 */
public class Main {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage:");
            System.err.println("  conjanalysis cdm <cdm_file> <combined_hbr_m> <output_json>");
            System.err.println("  conjanalysis direct <xm> <ym> <sigma_x> <sigma_y> <radius> <output_json>");
            System.exit(1);
        }

        String mode = args[0];

        if (mode.equals("direct")) {
            handleDirect(args);
        } else if (mode.equals("cdm")) {
            handleCdm(args);
        } else {
            System.err.println("Unknown mode: " + mode);
            System.exit(1);
        }
    }

    static void handleDirect(String[] args) throws Exception {
        if (args.length != 7) {
            System.err.println("direct mode requires: xm ym sigma_x sigma_y radius output_json");
            System.exit(1);
        }
        double xm = Double.parseDouble(args[1]);
        double ym = Double.parseDouble(args[2]);
        double sigmaX = Double.parseDouble(args[3]);
        double sigmaY = Double.parseDouble(args[4]);
        double radius = Double.parseDouble(args[5]);
        String outputJson = args[6];

        double pc = CollisionAnalyzer.computePc(xm, ym, sigmaX, sigmaY, radius);
        String risk = CollisionAnalyzer.classifyRisk(pc);

        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append(String.format("  \"xm\": %.17g,\n", xm));
        sb.append(String.format("  \"ym\": %.17g,\n", ym));
        sb.append(String.format("  \"sigma_x\": %.17g,\n", sigmaX));
        sb.append(String.format("  \"sigma_y\": %.17g,\n", sigmaY));
        sb.append(String.format("  \"radius\": %.17g,\n", radius));
        sb.append(String.format("  \"collision_probability\": %.17g,\n", pc));
        sb.append(String.format("  \"risk_level\": \"%s\"\n", risk));
        sb.append("}\n");
        writeFile(outputJson, sb.toString());
    }

    static void handleCdm(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("cdm mode requires: cdm_file combined_hbr_m output_json");
            System.exit(1);
        }
        String cdmFile = args[1];
        double combinedHbr = Double.parseDouble(args[2]);
        String outputJson = args[3];

        CdmData cdm = CdmParser.parse(cdmFile);
        CollisionAnalyzer.AnalysisResult result = CollisionAnalyzer.analyzeCdm(cdm, combinedHbr);

        String risk = CollisionAnalyzer.classifyRisk(result.collisionProbability);

        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append(String.format("  \"tca\": \"%s\",\n", cdm.tca));
        sb.append(String.format("  \"miss_distance_m\": %.17g,\n", cdm.missDistance));
        sb.append(String.format("  \"object1_name\": \"%s\",\n", cdm.name1));
        sb.append(String.format("  \"object2_name\": \"%s\",\n", cdm.name2));
        sb.append(String.format("  \"relative_velocity_km_s\": %.17g,\n", result.relativeVelocityKmS));
        sb.append(String.format("  \"collision_probability\": %.17g,\n", result.collisionProbability));
        sb.append(String.format("  \"risk_level\": \"%s\"\n", risk));
        sb.append("}\n");
        writeFile(outputJson, sb.toString());
    }

    static void writeFile(String path, String content) throws IOException {
        try (FileWriter fw = new FileWriter(path)) {
            fw.write(content);
        }
    }
}
