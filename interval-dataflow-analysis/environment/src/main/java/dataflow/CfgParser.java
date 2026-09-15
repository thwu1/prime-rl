package dataflow;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;

/**
 * Parses a .cfg text file into a CFG object.
 *
 * Format:
 *   # comment
 *   ENTRY B0
 *   VARS x y z
 *   BLOCK B0
 *     x = 5
 *     y = x + 3
 *     GOTO B1
 *   BLOCK B1 LOOP_HEADER
 *     BRANCH x < 10 B2 B3
 *   ...
 */
public class CfgParser {

    public static CFG parse(String filename) throws IOException {
        List<String> lines = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(new FileReader(filename))) {
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#")) {
                    lines.add(line);
                }
            }
        }

        String entryId = null;
        List<String> variables = new ArrayList<>();
        Set<String> varSet = new HashSet<>();
        Map<String, BasicBlock> blocks = new LinkedHashMap<>();
        List<String> blockOrder = new ArrayList<>();
        BasicBlock currentBlock = null;

        for (String line : lines) {
            if (line.startsWith("ENTRY ")) {
                entryId = line.substring(6).trim();
            } else if (line.startsWith("VARS ")) {
                String[] parts = line.substring(5).trim().split("\\s+");
                for (String v : parts) {
                    variables.add(v);
                    varSet.add(v);
                }
            } else if (line.startsWith("BLOCK ")) {
                String rest = line.substring(6).trim();
                String[] parts = rest.split("\\s+");
                String id = parts[0];
                boolean isLoop = parts.length > 1 && "LOOP_HEADER".equals(parts[1]);
                currentBlock = new BasicBlock(id, isLoop);
                blocks.put(id, currentBlock);
                blockOrder.add(id);
            } else if (currentBlock != null) {
                Instruction instr = parseInstruction(line, varSet);
                currentBlock.instructions.add(instr);
                if (instr.type == Instruction.Type.GOTO) {
                    if (!currentBlock.successorIds.contains(instr.gotoTarget)) {
                        currentBlock.successorIds.add(instr.gotoTarget);
                    }
                } else if (instr.type == Instruction.Type.BRANCH) {
                    if (!currentBlock.successorIds.contains(instr.trueTarget)) {
                        currentBlock.successorIds.add(instr.trueTarget);
                    }
                    if (!currentBlock.successorIds.contains(instr.falseTarget)) {
                        currentBlock.successorIds.add(instr.falseTarget);
                    }
                }
            }
        }

        // Build predecessor lists
        for (BasicBlock block : blocks.values()) {
            for (String succId : block.successorIds) {
                BasicBlock succ = blocks.get(succId);
                if (succ != null && !succ.predecessorIds.contains(block.id)) {
                    succ.predecessorIds.add(block.id);
                }
            }
        }

        Collections.sort(variables);
        return new CFG(entryId, variables, blocks, blockOrder);
    }

    private static boolean isInteger(String s) {
        if (s == null || s.isEmpty()) return false;
        int start = 0;
        if (s.charAt(0) == '-' || s.charAt(0) == '+') {
            if (s.length() == 1) return false;
            start = 1;
        }
        for (int i = start; i < s.length(); i++) {
            if (!Character.isDigit(s.charAt(i))) return false;
        }
        return true;
    }

    private static Instruction.Op parseOp(String s) {
        switch (s) {
            case "+": return Instruction.Op.ADD;
            case "-": return Instruction.Op.SUB;
            case "*": return Instruction.Op.MUL;
            case "/": return Instruction.Op.DIV;
            default: throw new IllegalArgumentException("Unknown operator: " + s);
        }
    }

    private static Instruction.Cmp parseCmp(String s) {
        switch (s) {
            case "<":  return Instruction.Cmp.LT;
            case "<=": return Instruction.Cmp.LE;
            case ">":  return Instruction.Cmp.GT;
            case ">=": return Instruction.Cmp.GE;
            case "==": return Instruction.Cmp.EQ;
            case "!=": return Instruction.Cmp.NE;
            default: throw new IllegalArgumentException("Unknown comparator: " + s);
        }
    }

    private static Instruction parseInstruction(String line, Set<String> vars) {
        String[] tokens = line.split("\\s+");

        if ("GOTO".equals(tokens[0])) {
            return new Instruction(Instruction.Type.GOTO,
                null, 0, null, null, null, 0, null, 0,
                null, null, null, 0, null, null, tokens[1]);
        }
        if ("RETURN".equals(tokens[0])) {
            return new Instruction(Instruction.Type.RETURN,
                null, 0, null, null, null, 0, null, 0,
                null, null, null, 0, null, null, null);
        }
        if ("NOP".equals(tokens[0])) {
            return new Instruction(Instruction.Type.NOP,
                null, 0, null, null, null, 0, null, 0,
                null, null, null, 0, null, null, null);
        }
        if ("BRANCH".equals(tokens[0])) {
            String condVar = tokens[1];
            Instruction.Cmp cmp = parseCmp(tokens[2]);
            String operand = tokens[3];
            String trueTarget = tokens[4];
            String falseTarget = tokens[5];
            if (isInteger(operand)) {
                return new Instruction(Instruction.Type.BRANCH,
                    null, 0, null, null, null, 0, null, 0,
                    condVar, cmp, null, Long.parseLong(operand),
                    trueTarget, falseTarget, null);
            } else {
                return new Instruction(Instruction.Type.BRANCH,
                    null, 0, null, null, null, 0, null, 0,
                    condVar, cmp, operand, 0,
                    trueTarget, falseTarget, null);
            }
        }

        // Assignment: dest = rhs
        String dest = tokens[0];
        // tokens[1] is "="

        if (tokens.length == 3) {
            String rhs = tokens[2];
            if ("?".equals(rhs)) {
                return new Instruction(Instruction.Type.UNKNOWN,
                    dest, 0, null, null, null, 0, null, 0,
                    null, null, null, 0, null, null, null);
            } else if (isInteger(rhs)) {
                return new Instruction(Instruction.Type.CONST,
                    dest, Long.parseLong(rhs), null, null, null, 0, null, 0,
                    null, null, null, 0, null, null, null);
            } else {
                return new Instruction(Instruction.Type.COPY,
                    dest, 0, rhs, null, null, 0, null, 0,
                    null, null, null, 0, null, null, null);
            }
        }

        if (tokens.length == 5) {
            // dest = left OP right
            String left = tokens[2];
            Instruction.Op op = parseOp(tokens[3]);
            String right = tokens[4];

            String leftVar = isInteger(left) ? null : left;
            long leftConst = isInteger(left) ? Long.parseLong(left) : 0;
            String rightVar = isInteger(right) ? null : right;
            long rightConst = isInteger(right) ? Long.parseLong(right) : 0;

            return new Instruction(Instruction.Type.BINOP,
                dest, 0, null, op, leftVar, leftConst, rightVar, rightConst,
                null, null, null, 0, null, null, null);
        }

        throw new IllegalArgumentException("Cannot parse instruction: " + line);
    }
}
