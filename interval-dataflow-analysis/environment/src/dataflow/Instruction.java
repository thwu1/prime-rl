package dataflow;

/**
 * Represents a single instruction in the 3-address IR.
 * Each basic block contains a list of instructions.
 */
public class Instruction {
    public enum Type {
        CONST,    // dest = constVal
        COPY,     // dest = src
        UNKNOWN,  // dest = ? (external unknown input)
        BINOP,    // dest = left op right
        GOTO,     // unconditional jump to gotoTarget
        BRANCH,   // conditional: if condVar cmp operand then trueTarget else falseTarget
        RETURN,   // end of function
        NOP       // no operation
    }

    public enum Op { ADD, SUB, MUL, DIV }

    public enum Cmp { LT, LE, GT, GE, EQ, NE }

    public final Type type;

    // Assignment destination (CONST, COPY, UNKNOWN, BINOP)
    public final String dest;

    // Constant value (CONST)
    public final long constVal;

    // Source variable (COPY)
    public final String src;

    // Binary operation (BINOP)
    public final Op op;
    public final String binopLeft;       // left variable name, null if left is a constant
    public final long binopLeftConst;     // left constant value (used when binopLeft is null)
    public final String binopRight;      // right variable name, null if right is a constant
    public final long binopRightConst;   // right constant value (used when binopRight is null)

    // Branch condition (BRANCH)
    public final String condVar;         // variable being tested
    public final Cmp cmp;               // comparison operator
    public final String condVar2;        // second variable (non-null for var-vs-var comparison)
    public final long condConst;         // constant operand (used when condVar2 is null)
    public final String trueTarget;      // target block if condition is true
    public final String falseTarget;     // target block if condition is false

    // Goto target (GOTO)
    public final String gotoTarget;

    Instruction(Type type, String dest, long constVal, String src,
                Op op, String binopLeft, long binopLeftConst,
                String binopRight, long binopRightConst,
                String condVar, Cmp cmp, String condVar2, long condConst,
                String trueTarget, String falseTarget, String gotoTarget) {
        this.type = type;
        this.dest = dest;
        this.constVal = constVal;
        this.src = src;
        this.op = op;
        this.binopLeft = binopLeft;
        this.binopLeftConst = binopLeftConst;
        this.binopRight = binopRight;
        this.binopRightConst = binopRightConst;
        this.condVar = condVar;
        this.cmp = cmp;
        this.condVar2 = condVar2;
        this.condConst = condConst;
        this.trueTarget = trueTarget;
        this.falseTarget = falseTarget;
        this.gotoTarget = gotoTarget;
    }

    @Override
    public String toString() {
        switch (type) {
            case CONST: return dest + " = " + constVal;
            case COPY: return dest + " = " + src;
            case UNKNOWN: return dest + " = ?";
            case BINOP: {
                String l = (binopLeft != null) ? binopLeft : String.valueOf(binopLeftConst);
                String r = (binopRight != null) ? binopRight : String.valueOf(binopRightConst);
                return dest + " = " + l + " " + op.name().toLowerCase().charAt(0) + " " + r;
            }
            case GOTO: return "GOTO " + gotoTarget;
            case BRANCH: {
                String operand = (condVar2 != null) ? condVar2 : String.valueOf(condConst);
                return "BRANCH " + condVar + " " + cmp + " " + operand + " " + trueTarget + " " + falseTarget;
            }
            case RETURN: return "RETURN";
            case NOP: return "NOP";
            default: return "???";
        }
    }
}
