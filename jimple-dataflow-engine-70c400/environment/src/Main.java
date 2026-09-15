public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java Main [--dot] <tac-file>");
            System.exit(1);
        }
        // TODO: Create your AnalysisEngine implementation and call analyze() or toDot()
        AnalysisEngine engine = null; // Replace with your implementation
        if (engine == null) {
            System.err.println("Error: AnalysisEngine not implemented");
            System.exit(1);
        }
        if (args[0].equals("--dot")) {
            if (args.length < 2) {
                System.err.println("Usage: java Main --dot <tac-file>");
                System.exit(1);
            }
            System.out.println(engine.toDot(args[1]));
        } else {
            System.out.println(engine.analyze(args[0]));
        }
    }
}
