package dataflow;

import java.util.*;

/**
 * Performs interval analysis on a CFG using worklist-based fixed-point iteration
 * with widening at loop headers and a subsequent narrowing pass.
 */
public class IntervalAnalyzer {
    private final CFG cfg;
    private final Map<String, IntervalStore> blockEntry;
    private final Map<String, IntervalStore> blockExit;
    // Edge states: from block -> to successor -> state
    private final Map<String, Map<String, IntervalStore>> edgeStates;
    private final Set<String> visited;

    public IntervalAnalyzer(CFG cfg) {
        this.cfg = cfg;
        this.blockEntry = new LinkedHashMap<>();
        this.blockExit = new LinkedHashMap<>();
        this.edgeStates = new LinkedHashMap<>();
        this.visited = new HashSet<>();
    }

    public void analyze() {
        // Initialize all blocks
        for (String blockId : cfg.blockOrder) {
            blockEntry.put(blockId, null); // null = unreachable
            blockExit.put(blockId, null);
            edgeStates.put(blockId, new LinkedHashMap<>());
        }

        // Phase 1: Ascending with widening
        // Entry block entry state is computed inside ascendingPhase
        ascendingPhase();

        // Phase 2: Descending with narrowing
        descendingPhase();
    }

    private void ascendingPhase() {
        Deque<String> worklist = new ArrayDeque<>();
        Set<String> inWorklist = new HashSet<>();
        worklist.add(cfg.entryId);
        inWorklist.add(cfg.entryId);

        while (!worklist.isEmpty()) {
            String blockId = worklist.poll();
            inWorklist.remove(blockId);
            BasicBlock block = cfg.blocks.get(blockId);

            // Compute entry state from predecessor edge states
            IntervalStore newEntry;
            if (blockId.equals(cfg.entryId)) {
                // Entry block: start with all vars = bot, then join with pred edges
                newEntry = new IntervalStore(cfg.variables);
                for (String predId : block.predecessorIds) {
                    IntervalStore edgeState = getEdgeState(predId, blockId);
                    newEntry = IntervalStore.join(newEntry, edgeState);
                }
            } else {
                newEntry = null;
                for (String predId : block.predecessorIds) {
                    IntervalStore edgeState = getEdgeState(predId, blockId);
                    newEntry = IntervalStore.join(newEntry, edgeState);
                }
            }

            if (newEntry == null) {
                // Block is unreachable
                continue;
            }

            // Apply widening at loop headers (not first visit)
            IntervalStore oldEntry = blockEntry.get(blockId);
            if (block.isLoopHeader && visited.contains(blockId) && oldEntry != null) {
                newEntry = oldEntry.widen(newEntry);
            }
            visited.add(blockId);

            // Check convergence
            if (oldEntry != null && newEntry.equals(oldEntry)) {
                continue;
            }

            blockEntry.put(blockId, newEntry);

            // Execute block
            processBlock(block, newEntry);

            // Add successors to worklist
            for (String succId : block.successorIds) {
                if (!inWorklist.contains(succId)) {
                    worklist.add(succId);
                    inWorklist.add(succId);
                }
            }
        }
    }

    private void descendingPhase() {
        // Run narrowing iterations until convergence
        boolean changed = true;
        int maxIter = 100;
        while (changed && maxIter-- > 0) {
            changed = false;
            for (String blockId : cfg.blockOrder) {
                BasicBlock block = cfg.blocks.get(blockId);
                IntervalStore oldEntry = blockEntry.get(blockId);
                if (oldEntry == null) continue; // skip unreachable

                // Recompute entry from predecessors
                IntervalStore newEntry;
                if (blockId.equals(cfg.entryId)) {
                    newEntry = new IntervalStore(cfg.variables);
                    for (String predId : block.predecessorIds) {
                        IntervalStore edgeState = getEdgeState(predId, blockId);
                        newEntry = IntervalStore.join(newEntry, edgeState);
                    }
                } else {
                    newEntry = null;
                    for (String predId : block.predecessorIds) {
                        IntervalStore edgeState = getEdgeState(predId, blockId);
                        newEntry = IntervalStore.join(newEntry, edgeState);
                    }
                }

                if (newEntry == null) continue;

                // Apply narrowing at loop headers
                if (block.isLoopHeader) {
                    newEntry = oldEntry.narrow(newEntry);
                }

                if (newEntry != null && !newEntry.equals(oldEntry)) {
                    blockEntry.put(blockId, newEntry);
                    processBlock(block, newEntry);
                    changed = true;
                }
            }
        }
    }

    private void processBlock(BasicBlock block, IntervalStore entryState) {
        // Execute instructions
        IntervalStore state = entryState.copy();
        Instruction lastBranch = null;

        for (Instruction instr : block.instructions) {
            switch (instr.type) {
                case CONST:
                    state.set(instr.dest, Interval.constant(instr.constVal));
                    break;
                case COPY:
                    state.set(instr.dest, state.get(instr.src));
                    break;
                case UNKNOWN:
                    state.set(instr.dest, Interval.TOP);
                    break;
                case BINOP:
                    executeBinop(state, instr);
                    break;
                case BRANCH:
                    lastBranch = instr;
                    break;
                case GOTO:
                case RETURN:
                case NOP:
                    break;
            }
        }

        blockExit.put(block.id, state);

        // Compute edge states
        if (lastBranch != null) {
            computeBranchEdges(block, state, lastBranch);
        } else {
            // GOTO or RETURN: propagate exit state unchanged
            for (String succId : block.successorIds) {
                edgeStates.get(block.id).put(succId, state.copy());
            }
        }
    }

    private void executeBinop(IntervalStore state, Instruction instr) {
        Interval left = (instr.binopLeft != null) ?
            state.get(instr.binopLeft) : Interval.constant(instr.binopLeftConst);
        Interval right = (instr.binopRight != null) ?
            state.get(instr.binopRight) : Interval.constant(instr.binopRightConst);

        Interval result;
        switch (instr.op) {
            case ADD: result = left.add(right); break;
            case SUB: result = left.sub(right); break;
            case MUL: result = left.mul(right); break;
            case DIV: result = left.div(right); break;
            default: result = Interval.TOP;
        }
        state.set(instr.dest, result);
    }

    private void computeBranchEdges(BasicBlock block, IntervalStore state,
                                     Instruction branch) {
        IntervalStore trueState = state.copy();
        IntervalStore falseState = state.copy();

        if (branch.condVar2 != null) {
            // Variable-to-variable comparison
            refineVarVar(trueState, falseState, branch.condVar,
                         branch.cmp, branch.condVar2);
        } else {
            // Variable-to-constant comparison
            refineVarConst(trueState, falseState, branch.condVar,
                           branch.cmp, branch.condConst);
        }

        // Check feasibility: if condition var is bot, the path is infeasible
        if (isInfeasible(trueState, branch)) {
            trueState = null;
        }
        if (isInfeasible(falseState, branch)) {
            falseState = null;
        }

        edgeStates.get(block.id).put(branch.trueTarget, trueState);
        edgeStates.get(block.id).put(branch.falseTarget, falseState);
    }

    private boolean isInfeasible(IntervalStore state, Instruction branch) {
        if (state == null) return true;
        if (state.get(branch.condVar).isBot()) return true;
        if (branch.condVar2 != null && state.get(branch.condVar2).isBot()) return true;
        return false;
    }

    private void refineVarConst(IntervalStore trueState, IntervalStore falseState,
                                 String var, Instruction.Cmp cmp, long c) {
        Interval cur = trueState.get(var);

        switch (cmp) {
            case LT:
                trueState.set(var, cur.meet(Interval.of(Interval.NEG_INF, c - 1)));
                falseState.set(var, cur.meet(Interval.of(c, Interval.POS_INF)));
                break;
            case LE:
                trueState.set(var, cur.meet(Interval.of(Interval.NEG_INF, c)));
                falseState.set(var, cur.meet(Interval.of(c + 1, Interval.POS_INF)));
                break;
            case GT:
                trueState.set(var, cur.meet(Interval.of(c + 1, Interval.POS_INF)));
                falseState.set(var, cur.meet(Interval.of(Interval.NEG_INF, c)));
                break;
            case GE:
                trueState.set(var, cur.meet(Interval.of(c, Interval.POS_INF)));
                falseState.set(var, cur.meet(Interval.of(Interval.NEG_INF, c - 1)));
                break;
            case EQ:
                trueState.set(var, cur.meet(Interval.constant(c)));
                // For false (!=): refine only at boundaries
                Interval falseCur = falseState.get(var);
                if (!falseCur.isBot() && falseCur.lo == c && falseCur.hi == c) {
                    falseState.set(var, Interval.BOT);
                } else if (!falseCur.isBot() && falseCur.lo == c) {
                    falseState.set(var, Interval.of(c + 1, falseCur.hi));
                } else if (!falseCur.isBot() && falseCur.hi == c) {
                    falseState.set(var, Interval.of(falseCur.lo, c - 1));
                }
                break;
            case NE:
                // True (!=): refine only at boundaries
                Interval trueCur = trueState.get(var);
                if (!trueCur.isBot() && trueCur.lo == c && trueCur.hi == c) {
                    trueState.set(var, Interval.BOT);
                } else if (!trueCur.isBot() && trueCur.lo == c) {
                    trueState.set(var, Interval.of(c + 1, trueCur.hi));
                } else if (!trueCur.isBot() && trueCur.hi == c) {
                    trueState.set(var, Interval.of(trueCur.lo, c - 1));
                }
                falseState.set(var, cur.meet(Interval.constant(c)));
                break;
        }
    }

    private void refineVarVar(IntervalStore trueState, IntervalStore falseState,
                               String var1, Instruction.Cmp cmp, String var2) {
        Interval i1 = trueState.get(var1);
        Interval i2 = trueState.get(var2);

        if (i1.isBot() || i2.isBot()) {
            // Can't refine with bot
            return;
        }

        switch (cmp) {
            case LT: // var1 < var2
                // True: var1 <= var2.hi - 1, var2 >= var1.lo + 1
                trueState.set(var1, i1.meet(Interval.of(Interval.NEG_INF, i2.hi - 1)));
                trueState.set(var2, i2.meet(Interval.of(i1.lo + 1, Interval.POS_INF)));
                // False: var1 >= var2.lo, var2 <= var1.hi
                falseState.set(var1, i1.meet(Interval.of(i2.lo, Interval.POS_INF)));
                falseState.set(var2, i2.meet(Interval.of(Interval.NEG_INF, i1.hi)));
                break;
            case LE:
                trueState.set(var1, i1.meet(Interval.of(Interval.NEG_INF, i2.hi)));
                trueState.set(var2, i2.meet(Interval.of(i1.lo, Interval.POS_INF)));
                falseState.set(var1, i1.meet(Interval.of(i2.lo + 1, Interval.POS_INF)));
                falseState.set(var2, i2.meet(Interval.of(Interval.NEG_INF, i1.hi - 1)));
                break;
            case GT:
                trueState.set(var1, i1.meet(Interval.of(i2.lo + 1, Interval.POS_INF)));
                trueState.set(var2, i2.meet(Interval.of(Interval.NEG_INF, i1.hi - 1)));
                falseState.set(var1, i1.meet(Interval.of(Interval.NEG_INF, i2.hi)));
                falseState.set(var2, i2.meet(Interval.of(i1.lo, Interval.POS_INF)));
                break;
            case GE:
                trueState.set(var1, i1.meet(Interval.of(i2.lo, Interval.POS_INF)));
                trueState.set(var2, i2.meet(Interval.of(Interval.NEG_INF, i1.hi)));
                falseState.set(var1, i1.meet(Interval.of(Interval.NEG_INF, i2.hi - 1)));
                falseState.set(var2, i2.meet(Interval.of(i1.lo + 1, Interval.POS_INF)));
                break;
            case EQ:
                // True: both must be in the intersection
                Interval meetBoth = i1.meet(i2);
                trueState.set(var1, meetBoth);
                trueState.set(var2, meetBoth);
                // False: can't refine precisely for intervals
                break;
            case NE:
                // True: can't refine precisely for intervals
                // False: both must be equal (intersection)
                Interval meetBothF = i1.meet(i2);
                falseState.set(var1, meetBothF);
                falseState.set(var2, meetBothF);
                break;
        }
    }

    private IntervalStore getEdgeState(String fromId, String toId) {
        Map<String, IntervalStore> edges = edgeStates.get(fromId);
        if (edges == null) return null;
        return edges.get(toId);
    }

    public Map<String, IntervalStore> getBlockEntry() { return blockEntry; }
    public Map<String, IntervalStore> getBlockExit() { return blockExit; }
}
