package modelchecker;

import java.util.*;


/**
 * A model checker for concurrent programs that performs DFS state-space
 * exploration with state memoization, detecting deadlocks, data races,
 * and assertion failures. Supports re-entrant locking and partial-order
 * reduction via ample sets.
 */
public class ModelChecker {
    private final boolean porEnabled;

    // Program structure
    private int numThreads;
    private int numVars;
    private int numLocks;
    private List<List<Statement>> programs;
    private String[] varNames;
    private String[] lockNames;
    private Map<String, Integer> varIndex;
    private Map<String, Integer> lockIndex;

    // Mutable execution state
    private int[] pc;
    private int[][] regs;       // regs[threadId][regIdx]
    private boolean[] halted;
    private int[] vars;
    private int[] lockOwner;    // -1 = free
    private int[] lockCount;    // re-entrancy depth

    // Exploration bookkeeping
    private Set<String> visited;
    private Set<String> reportedRaces;
    private Set<String> reportedAssertions;
    private List<Violation> violations;
    private int statesExplored;
    private int transitionsExplored;
    private List<String> currentTrace;

    private static final int NUM_REGS = 8;

    public ModelChecker(boolean porEnabled) {
        this.porEnabled = porEnabled;
    }

    public CheckerResult check(ConcurrentProgram program) {
        numThreads = program.threads.size();
        programs = program.threads;

        // Build variable index from initial values and all statements
        Set<String> allVars = new LinkedHashSet<>(program.initialValues.keySet());
        for (List<Statement> tp : programs) {
            for (Statement s : tp) {
                String v = s.getAccessedVar();
                if (v != null) allVars.add(v);
            }
        }
        varNames = allVars.toArray(new String[0]);
        numVars = varNames.length;
        varIndex = new HashMap<>();
        for (int i = 0; i < numVars; i++) varIndex.put(varNames[i], i);

        // Build lock index
        lockNames = program.locks.toArray(new String[0]);
        numLocks = lockNames.length;
        lockIndex = new HashMap<>();
        for (int i = 0; i < numLocks; i++) lockIndex.put(lockNames[i], i);

        // Initial execution state
        pc = new int[numThreads];
        regs = new int[numThreads][NUM_REGS];
        halted = new boolean[numThreads];
        vars = new int[numVars];
        lockOwner = new int[numLocks];
        lockCount = new int[numLocks];
        Arrays.fill(lockOwner, -1);
        for (Map.Entry<String, Integer> e : program.initialValues.entrySet()) {
            Integer idx = varIndex.get(e.getKey());
            if (idx != null) vars[idx] = e.getValue();
        }

        visited = new HashSet<>();
        reportedRaces = new HashSet<>();
        reportedAssertions = new HashSet<>();
        violations = new ArrayList<>();
        statesExplored = 0;
        transitionsExplored = 0;
        currentTrace = new ArrayList<>();

        explore();

        return new CheckerResult(violations, statesExplored, transitionsExplored);
    }

    // ---- DFS exploration ----

    private void explore() {
        String stateKey = encodeState();
        if (visited.contains(stateKey)) return;
        visited.add(stateKey);
        statesExplored++;

        List<Integer> enabled = getEnabledThreads();

        // Check deadlock: non-halted threads exist but none is enabled
        boolean anyNonHalted = false;
        for (int t = 0; t < numThreads; t++) {
            if (!halted[t]) { anyNonHalted = true; break; }
        }
        if (anyNonHalted && enabled.isEmpty()) {
            violations.add(new Violation(Violation.Type.DEADLOCK,
                buildDeadlockMessage(), new ArrayList<>(currentTrace)));
            return;
        }
        if (enabled.isEmpty()) return; // all halted, normal termination

        // Check data races at this state
        checkRaces(enabled);

        // Determine which threads to explore
        List<Integer> toExplore = porEnabled ? computeAmpleSet(enabled) : enabled;

        // Save state for backtracking
        int[] savedPc = pc.clone();
        int[][] savedRegs = cloneRegs();
        boolean[] savedHalted = halted.clone();
        int[] savedVars = vars.clone();
        int[] savedLockOwner = lockOwner.clone();
        int[] savedLockCount = lockCount.clone();

        for (int t : toExplore) {
            Statement stmt = programs.get(t).get(pc[t]);
            currentTrace.add("T" + t + ": " + stmt);

            executeStatement(t, stmt);
            transitionsExplored++;

            explore();

            // Backtrack
            currentTrace.remove(currentTrace.size() - 1);
            System.arraycopy(savedPc, 0, pc, 0, numThreads);
            restoreRegs(savedRegs);
            System.arraycopy(savedHalted, 0, halted, 0, numThreads);
            System.arraycopy(savedVars, 0, vars, 0, numVars);
            System.arraycopy(savedLockOwner, 0, lockOwner, 0, numLocks);
            System.arraycopy(savedLockCount, 0, lockCount, 0, numLocks);
        }
    }

    // ---- Enabled thread computation ----

    private List<Integer> getEnabledThreads() {
        List<Integer> enabled = new ArrayList<>();
        for (int t = 0; t < numThreads; t++) {
            if (halted[t]) continue;
            Statement stmt = programs.get(t).get(pc[t]);
            if (stmt.type == Statement.Type.LOCK) {
                Integer li = lockIndex.get(stmt.lock);
                if (li != null && lockOwner[li] != -1 && lockOwner[li] != t) {
                    continue; // blocked on lock held by another thread
                }
            }
            enabled.add(t);
        }
        return enabled;
    }

    // ---- Race detection ----

    private void checkRaces(List<Integer> enabled) {
        for (int i = 0; i < enabled.size(); i++) {
            int t1 = enabled.get(i);
            Statement s1 = programs.get(t1).get(pc[t1]);
            String v1 = s1.getAccessedVar();
            if (v1 == null) continue;

            for (int j = i + 1; j < enabled.size(); j++) {
                int t2 = enabled.get(j);
                Statement s2 = programs.get(t2).get(pc[t2]);
                String v2 = s2.getAccessedVar();
                if (v2 == null) continue;

                if (v1.equals(v2) && (s1.isWriteToVar() || s2.isWriteToVar())) {
                    String raceKey = v1 + ":" + Math.min(t1, t2) + ":" + Math.max(t1, t2);
                    if (reportedRaces.add(raceKey)) {
                        violations.add(new Violation(Violation.Type.DATA_RACE,
                            "concurrent access to " + v1 + " by thread " + t1 + " and thread " + t2,
                            new ArrayList<>(currentTrace)));
                    }
                }
            }
        }
    }

    // ---- Statement execution ----

    private void executeStatement(int tid, Statement stmt) {
        switch (stmt.type) {
            case READ: {
                Integer vi = varIndex.get(stmt.var);
                regs[tid][stmt.reg] = (vi != null) ? vars[vi] : 0;
                pc[tid]++;
                break;
            }
            case WRITE: {
                Integer vi = varIndex.get(stmt.var);
                if (vi == null) break;
                vars[vi] = (stmt.srcReg >= 0) ? regs[tid][stmt.srcReg] : stmt.imm;
                pc[tid]++;
                break;
            }
            case LOCK: {
                Integer li = lockIndex.get(stmt.lock);
                if (li != null) {
                    lockOwner[li] = tid;
                    lockCount[li]++;
                }
                pc[tid]++;
                break;
            }
            case UNLOCK: {
                Integer li = lockIndex.get(stmt.lock);
                if (li != null) {
                    lockCount[li]--;
                    if (lockCount[li] == 0) {
                        lockOwner[li] = -1;
                    }
                }
                pc[tid]++;
                break;
            }
            case SET: {
                regs[tid][stmt.reg] = stmt.imm;
                pc[tid]++;
                break;
            }
            case ADD: {
                regs[tid][stmt.reg] += stmt.imm;
                pc[tid]++;
                break;
            }
            case BEQ: {
                pc[tid] = (regs[tid][stmt.reg] == stmt.imm) ? stmt.target : pc[tid] + 1;
                break;
            }
            case BNE: {
                pc[tid] = (regs[tid][stmt.reg] != stmt.imm) ? stmt.target : pc[tid] + 1;
                break;
            }
            case ASSERT_EQ: {
                Integer vi = varIndex.get(stmt.var);
                int varVal = (vi != null) ? vars[vi] : 0;
                int regVal = regs[tid][stmt.reg];
                if (varVal != regVal) {
                    String assertKey = stmt.msg + ":" + tid + ":" + varVal + ":" + regVal;
                    if (reportedAssertions.add(assertKey)) {
                        violations.add(new Violation(Violation.Type.ASSERTION_FAILURE,
                            stmt.msg + " (expected " + regVal + " got " + varVal + ")",
                            new ArrayList<>(currentTrace)));
                    }
                }
                pc[tid]++;
                break;
            }
            case HALT: {
                halted[tid] = true;
                break;
            }
        }
    }

    // ---- Partial Order Reduction (ample sets) ----

    private List<Integer> computeAmpleSet(List<Integer> enabled) {
        if (enabled.size() <= 1) return enabled;

        // Try to find a singleton ample set: a thread whose next operation
        // is independent of ALL other enabled threads' next operations.
        for (int t : enabled) {
            Statement s = programs.get(t).get(pc[t]);
            boolean allIndependent = true;
            for (int other : enabled) {
                if (other == t) continue;
                Statement sOther = programs.get(other).get(pc[other]);
                if (areDependent(s, sOther)) {
                    allIndependent = false;
                    break;
                }
            }
            if (allIndependent) {
                return Collections.singletonList(t);
            }
        }

        // Try pairs: find two threads whose combined operations are
        // independent of all remaining threads.
        if (enabled.size() > 2) {
            for (int i = 0; i < enabled.size(); i++) {
                for (int j = i + 1; j < enabled.size(); j++) {
                    int t1 = enabled.get(i), t2 = enabled.get(j);
                    Statement s1 = programs.get(t1).get(pc[t1]);
                    Statement s2 = programs.get(t2).get(pc[t2]);
                    boolean pairIndependent = true;
                    for (int k = 0; k < enabled.size(); k++) {
                        if (k == i || k == j) continue;
                        int t3 = enabled.get(k);
                        Statement s3 = programs.get(t3).get(pc[t3]);
                        if (areDependent(s1, s3) || areDependent(s2, s3)) {
                            pairIndependent = false;
                            break;
                        }
                    }
                    if (pairIndependent) {
                        return Arrays.asList(t1, t2);
                    }
                }
            }
        }

        // No reduction possible; explore all enabled threads
        return enabled;
    }

    /**
     * Two operations are dependent if they access the same shared variable
     * with at least one write, or they access the same lock.
     */
    private boolean areDependent(Statement s1, Statement s2) {
        String v1 = s1.getAccessedVar(), v2 = s2.getAccessedVar();
        if (v1 != null && v2 != null && v1.equals(v2)) {
            if (s1.isWriteToVar() || s2.isWriteToVar()) {
                return true;
            }
        }
        String l1 = s1.getAccessedLock(), l2 = s2.getAccessedLock();
        if (l1 != null && l2 != null && l1.equals(l2)) {
            return true;
        }
        return false;
    }

    // ---- State encoding for memoization ----

    private String encodeState() {
        StringBuilder sb = new StringBuilder(64 + numThreads * (NUM_REGS + 2) * 4);
        for (int t = 0; t < numThreads; t++) {
            sb.append(pc[t]).append(',');
            sb.append(halted[t] ? '1' : '0').append(',');
            for (int r = 0; r < NUM_REGS; r++) {
                sb.append(regs[t][r]).append(',');
            }
        }
        for (int i = 0; i < numVars; i++) {
            sb.append(vars[i]).append(',');
        }
        for (int i = 0; i < numLocks; i++) {
            sb.append(lockOwner[i]).append(',');
            sb.append(lockCount[i]).append(',');
        }
        return sb.toString();
    }

    // ---- Helpers ----

    private String buildDeadlockMessage() {
        StringBuilder sb = new StringBuilder("all threads blocked:");
        for (int t = 0; t < numThreads; t++) {
            if (!halted[t]) {
                Statement s = programs.get(t).get(pc[t]);
                sb.append(" T").append(t).append(" waiting on ").append(s.lock);
            }
        }
        return sb.toString();
    }

    private int[][] cloneRegs() {
        int[][] copy = new int[numThreads][];
        for (int t = 0; t < numThreads; t++) {
            copy[t] = regs[t].clone();
        }
        return copy;
    }

    private void restoreRegs(int[][] saved) {
        for (int t = 0; t < numThreads; t++) {
            System.arraycopy(saved[t], 0, regs[t], 0, NUM_REGS);
        }
    }
}
