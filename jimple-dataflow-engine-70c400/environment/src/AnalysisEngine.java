public interface AnalysisEngine {
    /**
     * Parse a TAC file, run all three dataflow analyses,
     * and return the results as a JSON string.
     */
    String analyze(String tacFilePath) throws Exception;

    /**
     * Parse a TAC file, build the control-flow graph,
     * and return it in Graphviz DOT format.
     */
    String toDot(String tacFilePath) throws Exception;
}
