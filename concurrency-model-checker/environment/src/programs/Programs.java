package programs;

import modelchecker.*;
import java.util.*;


/**
 * Test programs for the model checker, each exhibiting a specific concurrency pattern.
 */
public class Programs {

    /**
     * Classic Dining Philosophers with 4 philosophers.
     * Each acquires left fork, then right fork, eats, releases both.
     */
    public static ConcurrentProgram diningPhilosophers() {
        int n = 4;
        List<List<Statement>> threads = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            String left = "fork_" + i;
            String right = "fork_" + ((i + 1) % n);
            threads.add(Arrays.asList(
                Statement.lock(left),       // 0: acquire left fork
                Statement.lock(right),      // 1: acquire right fork (may block)
                Statement.unlock(right),    // 2: release right fork
                Statement.unlock(left),     // 3: release left fork
                Statement.halt()            // 4: done
            ));
        }
        return new ConcurrentProgram("DiningPhilosophers", threads, Collections.emptyMap());
    }

    /**
     * Two threads writing to the same variable without synchronization.
     */
    public static ConcurrentProgram simpleRace() {
        Map<String, Integer> init = new HashMap<>();
        init.put("x", 0);
        List<List<Statement>> threads = Arrays.asList(
            Arrays.asList(Statement.writeImm("x", 1), Statement.halt()),
            Arrays.asList(Statement.writeImm("x", 2), Statement.halt())
        );
        return new ConcurrentProgram("SimpleRace", threads, init);
    }

    /**
     * Two threads incrementing a shared counter under the same lock.
     */
    public static ConcurrentProgram mutualExclusion() {
        Map<String, Integer> init = new HashMap<>();
        init.put("x", 0);
        List<List<Statement>> threads = Arrays.asList(
            Arrays.asList(
                Statement.lock("m"),
                Statement.read("x", 0),
                Statement.add(0, 1),
                Statement.writeReg("x", 0),
                Statement.unlock("m"),
                Statement.halt()
            ),
            Arrays.asList(
                Statement.lock("m"),
                Statement.read("x", 0),
                Statement.add(0, 1),
                Statement.writeReg("x", 0),
                Statement.unlock("m"),
                Statement.halt()
            )
        );
        return new ConcurrentProgram("MutualExclusion", threads, init);
    }

    /**
     * Two threads doing unsynchronized read-increment-write on a shared counter.
     */
    public static ConcurrentProgram raceCounter() {
        Map<String, Integer> init = new HashMap<>();
        init.put("counter", 0);
        List<List<Statement>> threads = Arrays.asList(
            Arrays.asList(
                Statement.read("counter", 0),
                Statement.add(0, 1),
                Statement.writeReg("counter", 0),
                Statement.halt()
            ),
            Arrays.asList(
                Statement.read("counter", 0),
                Statement.add(0, 1),
                Statement.writeReg("counter", 0),
                Statement.halt()
            )
        );
        return new ConcurrentProgram("RaceCounter", threads, init);
    }

    /**
     * Two threads acquiring two locks in opposite order.
     */
    public static ConcurrentProgram lockOrderDeadlock() {
        List<List<Statement>> threads = Arrays.asList(
            Arrays.asList(
                Statement.lock("alpha"),
                Statement.lock("beta"),
                Statement.unlock("beta"),
                Statement.unlock("alpha"),
                Statement.halt()
            ),
            Arrays.asList(
                Statement.lock("beta"),
                Statement.lock("alpha"),
                Statement.unlock("alpha"),
                Statement.unlock("beta"),
                Statement.halt()
            )
        );
        return new ConcurrentProgram("LockOrderDeadlock", threads, Collections.emptyMap());
    }

    /**
     * High-order race: per-field locking with non-atomic compound read.
     * Thread 0 copies fields a,b using per-field locks (individually synchronized).
     * Thread 1 modifies both fields atomically per-field but not together.
     * The compound copy can observe an inconsistent snapshot.
     */
    public static ConcurrentProgram highOrderRace() {
        Map<String, Integer> init = new HashMap<>();
        init.put("a", 42);
        init.put("b", 42);
        init.put("copy_a", 0);
        List<List<Statement>> threads = Arrays.asList(
            // Thread 0: copier
            Arrays.asList(
                Statement.lock("la"),           // 0
                Statement.read("a", 0),         // 1: r0 = a
                Statement.unlock("la"),         // 2
                Statement.lock("lb"),           // 3
                Statement.read("b", 1),         // 4: r1 = b
                Statement.unlock("lb"),         // 5
                Statement.writeReg("copy_a", 0),// 6: copy_a = r0 (snapshot of a)
                Statement.assertEq("copy_a", 1, "inconsistent copy: a != b"), // 7
                Statement.halt()                // 8
            ),
            // Thread 1: modifier
            Arrays.asList(
                Statement.lock("la"),           // 0
                Statement.writeImm("a", 41),    // 1: a = 41
                Statement.unlock("la"),         // 2
                Statement.lock("lb"),           // 3
                Statement.writeImm("b", 41),    // 4: b = 41
                Statement.unlock("lb"),         // 5
                Statement.halt()                // 6
            )
        );
        return new ConcurrentProgram("HighOrderRace", threads, init);
    }

    /**
     * Re-entrant locking: thread 0 acquires the same lock twice.
     * Thread 1 contends for the lock and may reset the shared variable.
     */
    public static ConcurrentProgram reentrantMutex() {
        Map<String, Integer> init = new HashMap<>();
        init.put("x", 0);
        List<List<Statement>> threads = Arrays.asList(
            // Thread 0: re-entrant locking with assertion
            Arrays.asList(
                Statement.lock("m"),           // 0: acquire outer
                Statement.lock("m"),           // 1: re-entrant acquire
                Statement.read("x", 0),        // 2: r0 = x
                Statement.add(0, 1),           // 3: r0++
                Statement.writeReg("x", 0),    // 4: x = r0
                Statement.unlock("m"),         // 5: inner release (depth 2->1)
                Statement.assertEq("x", 0, "x modified while lock held"),  // 6
                Statement.unlock("m"),         // 7: outer release (depth 1->0)
                Statement.halt()               // 8
            ),
            // Thread 1: contender that resets x
            Arrays.asList(
                Statement.lock("m"),           // 0
                Statement.writeImm("x", 0),    // 1: x = 0
                Statement.unlock("m"),         // 2
                Statement.halt()               // 3
            )
        );
        return new ConcurrentProgram("ReentrantMutex", threads, init);
    }

    /** Returns all test programs. */
    public static ConcurrentProgram[] all() {
        return new ConcurrentProgram[] {
            diningPhilosophers(),
            simpleRace(),
            mutualExclusion(),
            raceCounter(),
            lockOrderDeadlock(),
            highOrderRace(),
            reentrantMutex()
        };
    }
}
