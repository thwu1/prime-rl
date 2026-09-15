package modelchecker;

import java.util.*;


/**
 * Result of model-checking a concurrent program.
 */
public class CheckerResult {
    public final List<Violation> violations;
    public final int statesExplored;
    public final int transitionsExplored;

    public CheckerResult(List<Violation> violations, int statesExplored, int transitionsExplored) {
        this.violations = Collections.unmodifiableList(new ArrayList<>(violations));
        this.statesExplored = statesExplored;
        this.transitionsExplored = transitionsExplored;
    }
}
