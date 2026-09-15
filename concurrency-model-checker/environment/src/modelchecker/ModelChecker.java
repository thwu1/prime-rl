package modelchecker;


public class ModelChecker {
    private final boolean porEnabled;

    public ModelChecker(boolean porEnabled) {
        this.porEnabled = porEnabled;
    }

    /**
     * Check the given concurrent program for concurrency violations.
     *
     * @param program the concurrent program to verify
     * @return the checker result with all found violations and exploration statistics
     */
    public CheckerResult check(ConcurrentProgram program) {
        throw new UnsupportedOperationException("Not implemented");
    }
}
