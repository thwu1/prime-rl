package dataflow;

/**
 * Entry point for the interval analysis engine.
 *
 * Usage: java dataflow.Main <cfg-file>
 *
 * Must be completed to run interval analysis and output results.
 *
 * Output format (one line per block/position/variable, blocks in input order,
 * variables sorted alphabetically):
 *
 *   <block_id> entry <var> <interval>
 *   <block_id> exit <var> <interval>
 *
 * Where <interval> is one of:
 *   bot          — unreachable or undefined
 *   [-inf,inf]   — any integer
 *   [lo,hi]      — bounded interval (lo, hi are integers or -inf / inf)
 *
 * Example:
 *   B0 entry x bot
 *   B0 exit x [5,5]
 *   B0 exit y [8,8]
 */
public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("Usage: java dataflow.Main <cfg-file>");
            System.exit(1);
        }
        CFG cfg = CfgParser.parse(args[0]);

        // TODO: Implement interval analysis on this CFG.
        // 1. Build the interval abstract domain with widening and narrowing.
        // 2. Implement worklist-based fixed-point iteration.
        // 3. Apply widening at LOOP_HEADER blocks during ascending iteration.
        // 4. Apply narrowing during descending iteration for precision recovery.
        // 5. Refine intervals at conditional branches.
        // 6. Print results in the format described above.

        System.err.println("Interval analysis not yet implemented.");
        System.exit(1);
    }
}
