package modelchecker;

import java.util.*;


/**
 * Defines a concurrent program: a set of thread programs with
 * shared variable initial values. Lock names are inferred from statements.
 */
public class ConcurrentProgram {
    public final String name;
    public final List<List<Statement>> threads;
    public final Map<String, Integer> initialValues;
    public final Set<String> locks;

    public ConcurrentProgram(String name, List<List<Statement>> threads, Map<String, Integer> initialValues) {
        this.name = name;
        this.threads = Collections.unmodifiableList(threads);
        this.initialValues = Collections.unmodifiableMap(initialValues);

        Set<String> lockSet = new LinkedHashSet<>();
        for (Statement s : threads.get(0)) {
            String l = s.getAccessedLock();
            if (l != null) lockSet.add(l);
        }
        this.locks = Collections.unmodifiableSet(lockSet);
    }
}
