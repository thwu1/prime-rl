package dataflow;

import java.util.ArrayList;
import java.util.List;

/**
 * Represents a basic block in the control flow graph.
 */
public class BasicBlock {
    public final String id;
    public final boolean isLoopHeader;
    public final List<Instruction> instructions;
    public final List<String> successorIds;
    public final List<String> predecessorIds;

    public BasicBlock(String id, boolean isLoopHeader) {
        this.id = id;
        this.isLoopHeader = isLoopHeader;
        this.instructions = new ArrayList<>();
        this.successorIds = new ArrayList<>();
        this.predecessorIds = new ArrayList<>();
    }

    @Override
    public String toString() {
        return "BLOCK " + id + (isLoopHeader ? " LOOP_HEADER" : "");
    }
}
