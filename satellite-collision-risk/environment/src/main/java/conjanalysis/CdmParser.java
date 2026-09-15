package conjanalysis;

import java.io.*;

/**
 * Parser for CCSDS Conjunction Data Message (CDM) v1.0 keyword-value format.
 *
 */
public class CdmParser {

    public static CdmData parse(String filename) throws IOException {
        CdmData cdm = new CdmData();
        int currentObject = 0;

        try (BufferedReader br = new BufferedReader(new FileReader(filename))) {
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("COMMENT")) continue;

                int eqIdx = line.indexOf('=');
                if (eqIdx < 0) continue;

                String key = line.substring(0, eqIdx).trim();
                String val = line.substring(eqIdx + 1).trim();

                // Strip unit annotation [...]
                int bracket = val.indexOf('[');
                if (bracket >= 0) val = val.substring(0, bracket).trim();

                if (key.equals("OBJECT")) {
                    if (val.equals("OBJECT1")) currentObject = 1;
                    else if (val.equals("OBJECT2")) currentObject = 2;
                    continue;
                }

                if (key.equals("TCA")) { cdm.tca = val; continue; }
                if (key.equals("MISS_DIST")) { cdm.missDistance = Double.parseDouble(val); continue; }

                if (key.equals("OBJECT_NAME")) {
                    if (currentObject == 1) cdm.name1 = val;
                    else if (currentObject == 2) cdm.name2 = val;
                    continue;
                }

                double[] pos = (currentObject == 1) ? cdm.pos1 : cdm.pos2;
                double[] vel = (currentObject == 1) ? cdm.vel1 : cdm.vel2;
                double[][] cov = (currentObject == 1) ? cdm.cov1 : cdm.cov2;

                switch (key) {
                    case "X": pos[0] = Double.parseDouble(val); break;
                    case "Y": pos[1] = Double.parseDouble(val); break;
                    case "Z": pos[2] = Double.parseDouble(val); break;
                    case "X_DOT": vel[0] = Double.parseDouble(val); break;
                    case "Y_DOT": vel[1] = Double.parseDouble(val); break;
                    case "Z_DOT": vel[2] = Double.parseDouble(val); break;
                    case "CR_R":  cov[0][0] = Double.parseDouble(val); break;
                    case "CT_R":  cov[1][0] = Double.parseDouble(val); cov[0][1] = cov[1][0]; break;
                    case "CT_T":  cov[1][1] = Double.parseDouble(val); break;
                    case "CN_R":  cov[2][0] = Double.parseDouble(val); break;
                    case "CN_T":  cov[2][1] = Double.parseDouble(val); cov[1][2] = cov[2][1]; break;
                    case "CN_N":  cov[2][2] = Double.parseDouble(val); break;
                }
            }
        }
        return cdm;
    }
}
