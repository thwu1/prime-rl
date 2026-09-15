package modelchecker;

import java.util.*;


/**
 * Represents a concurrency violation found by the model checker.
 */
public class Violation {
    public enum Type { DEADLOCK, DATA_RACE, ASSERTION_FAILURE }

    public final Type type;
    public final String message;
    public final List<String> trace;

    public Violation(Type type, String message, List<String> trace) {
        this.type = type;
        this.message = message;
        this.trace = trace != null ? Collections.unmodifiableList(new ArrayList<>(trace)) : Collections.emptyList();
    }

    @Override
    public String toString() {
        return type + ": " + message;
    }
}
