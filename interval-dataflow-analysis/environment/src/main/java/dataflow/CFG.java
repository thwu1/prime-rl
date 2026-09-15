package dataflow;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
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

    /**
     * Serialize CFG structure metadata to a JSON string.
     */
    public String toJson() {
        JsonObject obj = new JsonObject();
        obj.addProperty("entry", entryId);
        obj.add("variables", new Gson().toJsonTree(variables));
        JsonArray blockArr = new JsonArray();
        for (String id : blockOrder) {
            JsonObject b = new JsonObject();
            b.addProperty("id", id);
            BasicBlock bb = blocks.get(id);
            b.addProperty("isLoopHeader", bb.isLoopHeader);
            b.addProperty("instructionCount", bb.instructions.size());
            b.add("successors", new Gson().toJsonTree(bb.successorIds));
            blockArr.add(b);
        }
        obj.add("blocks", blockArr);
        return new GsonBuilder().setPrettyPrinting().create().toJson(obj);
    }
}
