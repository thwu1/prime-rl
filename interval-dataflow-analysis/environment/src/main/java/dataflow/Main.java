package dataflow;

/**
 * Entry point for the interval analysis engine.
 *
 * Usage: java dataflow.Main <cfg-file> [json-output]
 *
 * Analyzes the given CFG and prints integer value ranges for all variables
 * at each program point.
 *
 * Text output format (stdout):
 *   <block_id> entry <var> <interval>
 *   <block_id> exit <var> <interval>
 *
 * Where <interval> is one of:
 *   bot          — unreachable or undefined
 *   [-inf,inf]   — any integer
 *   [lo,hi]      — bounded interval (lo, hi are integers or -inf / inf)
 *
 * If a second argument is given, writes a JSON report to that path using Gson.
 */
public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) {
            System.err.println("Usage: java dataflow.Main <cfg-file> [json-output]");
            System.exit(1);
        }
        CFG cfg = CfgParser.parse(args[0]);

        // TODO: Implement the analysis engine and output results.

        System.err.println("Analysis not yet implemented.");
        System.exit(1);
    }
}
