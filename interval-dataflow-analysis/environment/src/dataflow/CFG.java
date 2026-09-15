package dataflow;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Represents a control flow graph consisting of basic blocks.
 */
public class CFG {
    public final String entryId;
    public final List<String> variables;
    public final Map<String, BasicBlock> blocks;
    public final List<String> blockOrder;

    public CFG(String entryId, List<String> variables,
               Map<String, BasicBlock> blocks, List<String> blockOrder) {
        this.entryId = entryId;
        this.variables = Collections.unmodifiableList(variables);
        this.blocks = Collections.unmodifiableMap(blocks);
        this.blockOrder = Collections.unmodifiableList(blockOrder);
    }
}
