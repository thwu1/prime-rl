package modelchecker;


/**
 * Represents a single statement in a thread program for the model checker.
 * Statements operate on shared variables (read/write), locks (acquire/release),
 * thread-local registers (set/add/branch), or assertions.
 */
public class Statement {
    public enum Type {
        READ,       // registers[reg] = variables[var]
        WRITE,      // variables[var] = registers[srcReg] (if srcReg >= 0) or = imm
        LOCK,       // acquire lock (blocks if held by another thread)
        UNLOCK,     // release lock
        SET,        // registers[reg] = imm
        ADD,        // registers[reg] += imm
        BEQ,        // if registers[reg] == imm goto target
        BNE,        // if registers[reg] != imm goto target
        ASSERT_EQ,  // assert variables[var] == registers[reg], else violation
        HALT        // thread terminates
    }

    public final Type type;
    public final String var;      // shared variable name (READ, WRITE, ASSERT_EQ)
    public final String lock;     // lock name (LOCK, UNLOCK)
    public final int reg;         // register index (READ dest, ASSERT_EQ comparand, SET/ADD/BEQ/BNE target)
    public final int srcReg;      // source register for WRITE (-1 means use imm)
    public final int imm;         // immediate value (WRITE, SET, ADD, BEQ, BNE)
    public final int target;      // branch target PC (BEQ, BNE)
    public final String msg;      // assertion message (ASSERT_EQ)

    private Statement(Type type, String var, String lock, int reg, int srcReg, int imm, int target, String msg) {
        this.type = type;
        this.var = var;
        this.lock = lock;
        this.reg = reg;
        this.srcReg = srcReg;
        this.imm = imm;
        this.target = target;
        this.msg = msg;
    }

    // --- Static factory methods ---

    public static Statement read(String var, int destReg) {
        return new Statement(Type.READ, var, null, destReg, -1, 0, 0, null);
    }

    public static Statement writeReg(String var, int srcReg) {
        return new Statement(Type.WRITE, var, null, -1, srcReg, 0, 0, null);
    }

    public static Statement writeImm(String var, int value) {
        return new Statement(Type.WRITE, var, null, -1, -1, value, 0, null);
    }

    public static Statement lock(String lockName) {
        return new Statement(Type.LOCK, null, lockName, -1, -1, 0, 0, null);
    }

    public static Statement unlock(String lockName) {
        return new Statement(Type.UNLOCK, null, lockName, -1, -1, 0, 0, null);
    }

    public static Statement set(int reg, int value) {
        return new Statement(Type.SET, null, null, reg, -1, value, 0, null);
    }

    public static Statement add(int reg, int delta) {
        return new Statement(Type.ADD, null, null, reg, -1, delta, 0, null);
    }

    public static Statement beq(int reg, int value, int targetPc) {
        return new Statement(Type.BEQ, null, null, reg, -1, value, targetPc, null);
    }

    public static Statement bne(int reg, int value, int targetPc) {
        return new Statement(Type.BNE, null, null, reg, -1, value, targetPc, null);
    }

    public static Statement assertEq(String var, int reg, String message) {
        return new Statement(Type.ASSERT_EQ, var, null, reg, -1, 0, 0, message);
    }

    public static Statement halt() {
        return new Statement(Type.HALT, null, null, -1, -1, 0, 0, null);
    }

    // --- Dependency analysis helpers (for POR) ---

    /** Returns the shared variable accessed by this statement, or null. */
    public String getAccessedVar() {
        switch (type) {
            case READ: case WRITE: case ASSERT_EQ: return var;
            default: return null;
        }
    }

    /** Returns the lock accessed by this statement, or null. */
    public String getAccessedLock() {
        switch (type) {
            case LOCK: case UNLOCK: return lock;
            default: return null;
        }
    }

    /** Returns true if this statement writes to a shared variable. */
    public boolean isWriteToVar() {
        return type == Type.WRITE;
    }

    @Override
    public String toString() {
        switch (type) {
            case READ:      return "READ " + var + " -> r" + reg;
            case WRITE:     return srcReg >= 0 ? "WRITE " + var + " <- r" + srcReg : "WRITE " + var + " = " + imm;
            case LOCK:      return "LOCK " + lock;
            case UNLOCK:    return "UNLOCK " + lock;
            case SET:       return "SET r" + reg + " = " + imm;
            case ADD:       return "ADD r" + reg + " += " + imm;
            case BEQ:       return "BEQ r" + reg + " == " + imm + " goto " + target;
            case BNE:       return "BNE r" + reg + " != " + imm + " goto " + target;
            case ASSERT_EQ: return "ASSERT " + var + " == r" + reg + " [" + msg + "]";
            case HALT:      return "HALT";
            default:        return "?";
        }
    }
}
