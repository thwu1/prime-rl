import java.io.*;
import java.util.*;
import java.util.stream.*;

/**
 * Complete implementation of the intraprocedural dataflow analysis engine.
 * Implements reaching definitions, live variables, and available expressions.
 *
 */
public class DataflowSolver implements AnalysisEngine {

    // ==================== Statement Representation ====================

    static class Stmt {
        int index;
        String text;
        String defVar;
        Set<String> useVars = new LinkedHashSet<>();
        // Binary op info
        String operator;
        String leftOp, rightOp;
        boolean leftIsVar, rightIsVar;
        // Control flow
        String targetLabel;
        boolean isGoto, isIf, isReturn;

        Stmt(int index, String text) {
            this.index = index;
            this.text = text;
        }
    }

    // ==================== Instance State ====================

    private String methodName;
    private List<Stmt> stmts;
    private Map<String, Integer> labelMap;
    private int[][] succ, pred;
    private int numStmts;

    // Analysis results (sets encoded as strings)
    private Set<String>[] rdIn, rdOut;   // "var:idx"
    private Set<String>[] lvIn, lvOut;   // "varname"
    private Set<String>[] aeIn, aeOut;   // "left op right"

    // ==================== Parsing ====================

    private static boolean isIntLiteral(String s) {
        if (s == null || s.isEmpty()) return false;
        int start = (s.charAt(0) == '-') ? 1 : 0;
        if (start >= s.length()) return false;
        for (int i = start; i < s.length(); i++) {
            if (!Character.isDigit(s.charAt(i))) return false;
        }
        return true;
    }

    private static boolean isArithOp(String s) {
        return "+".equals(s) || "-".equals(s) || "*".equals(s) || "/".equals(s);
    }

    private void parse(String path) throws IOException {
        stmts = new ArrayList<>();
        labelMap = new HashMap<>();

        List<String> lines = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#")) lines.add(line);
            }
        }

        methodName = "";
        int start = 0;
        if (!lines.isEmpty() && lines.get(0).startsWith("method ")) {
            String m = lines.get(0);
            int p = m.indexOf('(');
            methodName = m.substring(7, p).trim();
            start = 1;
        }

        // Separate labels from statements
        List<Object[]> items = new ArrayList<>();
        for (int i = start; i < lines.size(); i++) {
            String line = lines.get(i);
            if (isLabel(line)) {
                items.add(new Object[]{"label", line.substring(0, line.length() - 1).trim()});
            } else {
                items.add(new Object[]{"stmt", line});
            }
        }

        // Map labels to the index of the next statement
        int idx = 0;
        for (Object[] item : items) {
            if ("label".equals(item[0])) {
                labelMap.put((String) item[1], idx);
            } else {
                idx++;
            }
        }

        // Parse statements
        for (Object[] item : items) {
            if ("stmt".equals(item[0])) {
                stmts.add(parseStmt(stmts.size(), (String) item[1]));
            }
        }

        numStmts = stmts.size();
    }

    private static boolean isLabel(String line) {
        return line.endsWith(":")
            && !line.contains("=")
            && !line.startsWith("if ")
            && !line.startsWith("goto ")
            && !line.startsWith("return");
    }

    private Stmt parseStmt(int index, String line) {
        Stmt s = new Stmt(index, line);

        if (line.startsWith("if ")) {
            s.isIf = true;
            int gi = line.indexOf(" goto ");
            String cond = line.substring(3, gi).trim();
            s.targetLabel = line.substring(gi + 6).trim();
            String[] parts = cond.split("\\s+");
            if (parts.length >= 1 && !isIntLiteral(parts[0])) s.useVars.add(parts[0]);
            if (parts.length >= 3 && !isIntLiteral(parts[2])) s.useVars.add(parts[2]);
        } else if (line.startsWith("goto ")) {
            s.isGoto = true;
            s.targetLabel = line.substring(5).trim();
        } else if (line.startsWith("return")) {
            s.isReturn = true;
            String rest = line.substring(6).trim();
            if (!rest.isEmpty() && !isIntLiteral(rest)) {
                s.useVars.add(rest);
            }
        } else if (line.contains(" = ")) {
            int eq = line.indexOf(" = ");
            s.defVar = line.substring(0, eq).trim();
            String rhs = line.substring(eq + 3).trim();
            String[] tokens = rhs.split("\\s+");
            if (tokens.length == 3 && isArithOp(tokens[1])) {
                s.operator = tokens[1];
                s.leftOp = tokens[0];
                s.rightOp = tokens[2];
                s.leftIsVar = !isIntLiteral(tokens[0]);
                s.rightIsVar = !isIntLiteral(tokens[2]);
                if (s.leftIsVar) s.useVars.add(tokens[0]);
                if (s.rightIsVar) s.useVars.add(tokens[2]);
            } else if (tokens.length == 1 && !isIntLiteral(tokens[0])) {
                // Copy: x = y
                s.useVars.add(tokens[0]);
            }
        }

        return s;
    }

    // ==================== CFG Construction ====================

    private void buildCFG() {
        succ = new int[numStmts][];
        for (int i = 0; i < numStmts; i++) {
            Stmt s = stmts.get(i);
            List<Integer> targets = new ArrayList<>();
            if (s.isGoto) {
                targets.add(labelMap.get(s.targetLabel));
            } else if (s.isIf) {
                if (i + 1 < numStmts) targets.add(i + 1); // fall-through
                targets.add(labelMap.get(s.targetLabel));   // branch
            } else if (s.isReturn) {
                // no successors
            } else {
                if (i + 1 < numStmts) targets.add(i + 1); // fall-through
            }
            succ[i] = targets.stream().mapToInt(Integer::intValue).toArray();
        }

        // Build predecessors from successors
        List<List<Integer>> preds = new ArrayList<>();
        for (int i = 0; i < numStmts; i++) preds.add(new ArrayList<>());
        for (int i = 0; i < numStmts; i++) {
            for (int s : succ[i]) {
                preds.get(s).add(i);
            }
        }
        pred = new int[numStmts][];
        for (int i = 0; i < numStmts; i++) {
            pred[i] = preds.get(i).stream().mapToInt(Integer::intValue).toArray();
        }
    }

    // ==================== Reaching Definitions ====================

    @SuppressWarnings("unchecked")
    private void reachingDefs() {
        // Collect all definitions per variable
        Map<String, Set<String>> allDefsOf = new HashMap<>();
        for (Stmt s : stmts) {
            if (s.defVar != null) {
                allDefsOf.computeIfAbsent(s.defVar, k -> new HashSet<>())
                         .add(s.defVar + ":" + s.index);
            }
        }

        // Compute GEN and KILL
        Set<String>[] gen = new HashSet[numStmts];
        Set<String>[] kill = new HashSet[numStmts];
        for (int i = 0; i < numStmts; i++) {
            gen[i] = new HashSet<>();
            kill[i] = new HashSet<>();
            Stmt s = stmts.get(i);
            if (s.defVar != null) {
                String def = s.defVar + ":" + i;
                gen[i].add(def);
                Set<String> defs = allDefsOf.getOrDefault(s.defVar, Collections.emptySet());
                for (String d : defs) {
                    if (!d.equals(def)) kill[i].add(d);
                }
            }
        }

        // Initialize
        rdIn = new HashSet[numStmts];
        rdOut = new HashSet[numStmts];
        for (int i = 0; i < numStmts; i++) {
            rdIn[i] = new HashSet<>();
            rdOut[i] = new HashSet<>(gen[i]);
        }

        // Forward worklist with union merge
        Deque<Integer> wl = new ArrayDeque<>();
        boolean[] inWl = new boolean[numStmts];
        for (int i = 0; i < numStmts; i++) { wl.add(i); inWl[i] = true; }

        while (!wl.isEmpty()) {
            int i = wl.poll();
            inWl[i] = false;

            // IN = union of predecessors' OUT
            Set<String> newIn = new HashSet<>();
            for (int p : pred[i]) newIn.addAll(rdOut[p]);
            rdIn[i] = newIn;

            // OUT = (IN - KILL) U GEN
            Set<String> newOut = new HashSet<>(rdIn[i]);
            newOut.removeAll(kill[i]);
            newOut.addAll(gen[i]);

            if (!newOut.equals(rdOut[i])) {
                rdOut[i] = newOut;
                for (int s : succ[i]) {
                    if (!inWl[s]) { wl.add(s); inWl[s] = true; }
                }
            }
        }
    }

    // ==================== Live Variables ====================

    @SuppressWarnings("unchecked")
    private void liveVars() {
        // DEF and USE per statement
        Set<String>[] def = new HashSet[numStmts];
        Set<String>[] use = new HashSet[numStmts];
        for (int i = 0; i < numStmts; i++) {
            Stmt s = stmts.get(i);
            def[i] = new HashSet<>();
            use[i] = new HashSet<>(s.useVars);
            if (s.defVar != null) def[i].add(s.defVar);
        }

        // Initialize
        lvIn = new HashSet[numStmts];
        lvOut = new HashSet[numStmts];
        for (int i = 0; i < numStmts; i++) {
            lvIn[i] = new HashSet<>(use[i]);
            lvOut[i] = new HashSet<>();
        }

        // Backward worklist with union merge
        Deque<Integer> wl = new ArrayDeque<>();
        boolean[] inWl = new boolean[numStmts];
        for (int i = 0; i < numStmts; i++) { wl.add(i); inWl[i] = true; }

        while (!wl.isEmpty()) {
            int i = wl.poll();
            inWl[i] = false;

            // OUT = union of successors' IN
            Set<String> newOut = new HashSet<>();
            for (int s : succ[i]) newOut.addAll(lvIn[s]);
            lvOut[i] = newOut;

            // IN = (OUT - DEF) U USE
            Set<String> newIn = new HashSet<>(lvOut[i]);
            newIn.removeAll(def[i]);
            newIn.addAll(use[i]);

            if (!newIn.equals(lvIn[i])) {
                lvIn[i] = newIn;
                for (int p : pred[i]) {
                    if (!inWl[p]) { wl.add(p); inWl[p] = true; }
                }
            }
        }
    }

    // ==================== Available Expressions ====================

    @SuppressWarnings("unchecked")
    private void availExprs() {
        // Collect universe of expressions: all "var OP var" in binary assignments
        Set<String> universe = new LinkedHashSet<>();
        for (Stmt s : stmts) {
            if (s.operator != null && s.leftIsVar && s.rightIsVar) {
                universe.add(s.leftOp + " " + s.operator + " " + s.rightOp);
            }
        }

        // GEN and KILL per statement
        Set<String>[] gen = new HashSet[numStmts];
        Set<String>[] kill = new HashSet[numStmts];
        for (int i = 0; i < numStmts; i++) {
            gen[i] = new HashSet<>();
            kill[i] = new HashSet<>();
            Stmt s = stmts.get(i);

            if (s.defVar != null) {
                // Kill all expressions containing the defined variable
                for (String expr : universe) {
                    String[] parts = expr.split(" ");
                    if (parts[0].equals(s.defVar) || parts[2].equals(s.defVar)) {
                        kill[i].add(expr);
                    }
                }
                // Gen: binary op with two var operands, defined var not in operands
                if (s.operator != null && s.leftIsVar && s.rightIsVar
                    && !s.defVar.equals(s.leftOp) && !s.defVar.equals(s.rightOp)) {
                    gen[i].add(s.leftOp + " " + s.operator + " " + s.rightOp);
                }
            }
        }

        // Initialize
        aeIn = new HashSet[numStmts];
        aeOut = new HashSet[numStmts];

        // Entry: in = {}, out = gen[0]
        aeIn[0] = new HashSet<>();
        Set<String> entryOut = new HashSet<>();
        entryOut.addAll(gen[0]);
        aeOut[0] = entryOut;

        // Non-entry: initialize to universal set
        for (int i = 1; i < numStmts; i++) {
            aeIn[i] = new HashSet<>(universe);
            Set<String> out = new HashSet<>(universe);
            out.removeAll(kill[i]);
            out.addAll(gen[i]);
            aeOut[i] = out;
        }

        // Forward worklist with intersection merge
        Deque<Integer> wl = new ArrayDeque<>();
        boolean[] inWl = new boolean[numStmts];
        for (int i = 0; i < numStmts; i++) { wl.add(i); inWl[i] = true; }

        while (!wl.isEmpty()) {
            int i = wl.poll();
            inWl[i] = false;

            // IN = intersection of predecessors' OUT
            Set<String> newIn;
            if (pred[i].length == 0) {
                if (i == 0) {
                    newIn = new HashSet<>(); // entry: empty
                } else {
                    newIn = new HashSet<>(universe); // unreachable: universal
                }
            } else {
                newIn = null;
                for (int p : pred[i]) {
                    if (newIn == null) {
                        newIn = new HashSet<>(aeOut[p]);
                    } else {
                        newIn.retainAll(aeOut[p]);
                    }
                }
            }
            aeIn[i] = newIn;

            // OUT = (IN - KILL) U GEN
            Set<String> newOut = new HashSet<>(aeIn[i]);
            newOut.removeAll(kill[i]);
            newOut.addAll(gen[i]);

            if (!newOut.equals(aeOut[i])) {
                aeOut[i] = newOut;
                for (int s : succ[i]) {
                    if (!inWl[s]) { wl.add(s); inWl[s] = true; }
                }
            }
        }
    }

    // ==================== DOT CFG Output ====================

    private String buildDot() {
        StringBuilder sb = new StringBuilder();
        sb.append("digraph ").append(methodName).append(" {\n");
        for (Stmt s : stmts) {
            sb.append("  ").append(s.index)
              .append(" [label=\"").append(s.index).append(": ")
              .append(escDot(s.text)).append("\"];\n");
        }
        for (int i = 0; i < numStmts; i++) {
            for (int j : succ[i]) {
                sb.append("  ").append(i).append(" -> ").append(j).append(";\n");
            }
        }
        sb.append("}\n");
        return sb.toString();
    }

    private static String escDot(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    // ==================== JSON Output ====================

    private String toJson() {
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"method\": \"").append(escJson(methodName)).append("\",\n");

        // Statements
        sb.append("  \"statements\": [");
        for (int i = 0; i < numStmts; i++) {
            if (i > 0) sb.append(", ");
            sb.append("\"").append(escJson(stmts.get(i).text)).append("\"");
        }
        sb.append("],\n");

        // Reaching Definitions
        sb.append("  \"reaching_definitions\": {\n");
        sb.append("    \"in\": ").append(rdToJson(rdIn)).append(",\n");
        sb.append("    \"out\": ").append(rdToJson(rdOut)).append("\n");
        sb.append("  },\n");

        // Live Variables
        sb.append("  \"live_variables\": {\n");
        sb.append("    \"in\": ").append(strSetToJson(lvIn)).append(",\n");
        sb.append("    \"out\": ").append(strSetToJson(lvOut)).append("\n");
        sb.append("  },\n");

        // Available Expressions
        sb.append("  \"available_expressions\": {\n");
        sb.append("    \"in\": ").append(strSetToJson(aeIn)).append(",\n");
        sb.append("    \"out\": ").append(strSetToJson(aeOut)).append("\n");
        sb.append("  }\n");

        sb.append("}");
        return sb.toString();
    }

    private String rdToJson(Set<String>[] sets) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < sets.length; i++) {
            if (i > 0) sb.append(", ");
            // Parse "var:idx" pairs and sort
            List<String[]> sorted = sets[i].stream()
                .map(s -> s.split(":"))
                .sorted((a, b) -> {
                    int cmp = a[0].compareTo(b[0]);
                    return cmp != 0 ? cmp : Integer.compare(Integer.parseInt(a[1]), Integer.parseInt(b[1]));
                })
                .collect(Collectors.toList());
            sb.append("[");
            for (int j = 0; j < sorted.size(); j++) {
                if (j > 0) sb.append(", ");
                sb.append("[\"").append(sorted.get(j)[0]).append("\", ").append(sorted.get(j)[1]).append("]");
            }
            sb.append("]");
        }
        sb.append("]");
        return sb.toString();
    }

    private String strSetToJson(Set<String>[] sets) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < sets.length; i++) {
            if (i > 0) sb.append(", ");
            List<String> sorted = sets[i].stream().sorted().collect(Collectors.toList());
            sb.append("[");
            for (int j = 0; j < sorted.size(); j++) {
                if (j > 0) sb.append(", ");
                sb.append("\"").append(escJson(sorted.get(j))).append("\"");
            }
            sb.append("]");
        }
        sb.append("]");
        return sb.toString();
    }

    private static String escJson(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    // ==================== Main Entry Points ====================

    @Override
    public String analyze(String tacFilePath) throws Exception {
        parse(tacFilePath);
        buildCFG();
        reachingDefs();
        liveVars();
        availExprs();
        return toJson();
    }

    @Override
    public String toDot(String tacFilePath) throws Exception {
        parse(tacFilePath);
        buildCFG();
        return buildDot();
    }
}
