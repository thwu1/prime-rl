/* MicroJava Code Generator  (HM 23-10-02)
   ========================
	 This class holds the code buffer with its access primitives put, put2, and put4.
	 It also holds methods to load operands and to generate complex instructions
	 such as assignments, calls and jumps.
--------------------------------------------------------------------------------*/

package MJ.CodeGen;

import java.io.*;
import MJ.*;
import MJ.SymTab.*;

public class Code {
	public static final int  // instruction codes
		load        =  1,
		load0       =  2,
		load1       =  3,
		load2       =  4,
		load3       =  5,
		store       =  6,
		store0      =  7,
		store1      =  8,
		store2      =  9,
		store3      = 10,
		getstatic   = 11,
		putstatic   = 12,
		getfield    = 13,
		putfield    = 14,
		const0      = 15,
		const1      = 16,
		const2      = 17,
		const3      = 18,
		const4      = 19,
		const5      = 20,
		const_m1    = 21,
		const_      = 22,
		add         = 23,
		sub         = 24,
		mul         = 25,
		div         = 26,
		rem         = 27,
		neg         = 28,
		shl         = 29,
		shr         = 30,
		inc         = 31,
		new_        = 32,
		newarray    = 33,
		aload       = 34,
		astore      = 35,
		baload      = 36,
		bastore     = 37,
		arraylength = 38,
		pop         = 39,
		dup         = 40,
		dup2        = 41,
		jmp         = 42,
		jeq         = 43,
		jne         = 44,
		jlt         = 45,
		jle         = 46,
		jgt         = 47,
		jge         = 48,
		call        = 49,
		return_     = 50,
		enter       = 51,
		exit        = 52,
		read        = 53,
		print       = 54,
		bread       = 55,
		bprint      = 56,
		trap		    = 57;

	public static final int  // compare operators
		eq = 0,
		ne = 1,
		lt = 2,
		le = 3,
		gt = 4,
		ge = 5;

	private static int[] inverse = {ne, eq, ge, gt, le, lt};
	private static final int bufSize = 8192;

	private static byte[] code;	// code buffer
	public static int pc;				// next free byte in code buffer
	public static int mainPc;		// pc of main function (set by the parser)
	public static int dataSize;	// length of static data in words (set by parser)

	private static void error(String msg) {
		Parser.error(msg);
	}

	//------------------ code buffer access ------------------------

	// Appends a byte to the code buffer
	public static void put(int x) {
		if (pc >= bufSize) {
			if (pc == bufSize) error("program too large");
			pc++;
		} else
			code[pc++] = (byte)x;
	}

	// Appends 2 bytes to the code buffer
	public static void put2(int x) {
		put(x>>8); put(x);
	}

	// Writes 2 bytes at position pos into the code buffer
	public static void put2(int pos, int x) {
		int oldpc = pc; pc = pos; put2(x); pc = oldpc;
	}

	// Appends 4 bytes to the code buffer
	public static void put4(int x) {
		put2(x>>16); put2(x);
	}

	//------------------- instruction generation -------------------

	// Loads the operand x to the expression stack
	public static void load(Operand x) {
		switch (x.kind) {
			case Operand.Con: {
				if (x.type == Tab.nullType) put(const0);
				else if (0 <= x.val && x.val <= 5) put(const0 + x.val);
				else if (x.val == -1) put(const_m1);
				else {put(const_); put4(x.val);}
				break;
			}
			case Operand.Static: {
				put(getstatic); put2(x.adr);
				break;
			}
			case Operand.Local: {
				if (0 <= x.adr && x.adr <= 3) put(load0 + x.adr);
				else {put(load); put(x.adr);}
				break;
			}
			case Operand.Fld: {
				put(getfield); put2(x.adr);
				break;
			}
			case Operand.Elem: {
				if (x.type.kind == Struct.Char) put(baload); else put(aload);
				break;
			}
			case Operand.Stack: // nothing (already loaded)
				break;
			case Operand.Meth: // should never happen
			case Operand.Cond:
				error("cannot load this");
				break;
		}
		x.kind = Operand.Stack;
	}

	// Generates an assignment x = y; y has already been loaded
	public static void assignTo(Operand x) {
		switch (x.kind) {
			case Operand.Local: {
				if (0 <= x.adr && x.adr <= 3) put(store0 + x.adr);
				else {put(store); put(x.adr);}
				break;
			}
			case Operand.Static: {
				put(putstatic); put2(x.adr);
				break;
			}
			case Operand.Fld: {
				put(putfield); put2(x.adr);
				break;
			}
			case Operand.Elem: {
				if (x.type.kind == Struct.Char) put(bastore); else put(astore);
				break;
			}
			default:
				error("can only assign to a designator");
				break;
		}
	}

	// Calls method m
	public static void callMethod (Operand m) {
		if (m.obj == Tab.ordObj || m.obj == Tab.chrObj) ;  // nothing
		else if (m.obj == Tab.lenObj)         // inline len function
			put(arraylength);
		else {
			put(call); put2(m.adr - (pc - 1));  // call with relative offset
		}
	}

	// Increments or decrements x; val is +/-1
	public static void inc(Operand x, int val) {
		if (x.type != Tab.intType) error("designator of type int expected");
		switch (x.kind) {
			case Operand.Local:
				put(inc); put(x.adr); put(val);
				break;
			case Operand.Static:
				put(getstatic); put2(x.adr);
				if (val == 1) put(const1); else put(const_m1);
				put(add);
				put(putstatic); put2(x.adr);
				break;
			case Operand.Fld:
				put(dup);
				put(getfield); put2(x.adr);
				if (val == 1) put(const1); else put(const_m1);
				put(add);
				put(putfield); put2(x.adr);
				break;
			case Operand.Elem:
				put(dup2);
				put(aload); // must be an int array (already checked above)
				if (val == 1) put(const1); else put(const_m1);
				put(add);
				put(astore);
				break;
			default:
				error("++ or -- not applicable");
				break;
		}
	}

	//--------------------------- jumps -----------------------------

	// Unconditional jump
	public static void jump(Label lab) {
		put(jmp); lab.putAdr();
	}

	// Conditional true-jump (jump if comparison with op is true)
	public static void tJump (int op, Label label) {
		put(jeq + op);  // jeq, jne, jlt, jle, jgt, jge
		label.putAdr();
	}

	// Conditional false-jump (jump if comparison with op is false)
	public static void fJump (int op, Label label) {
		put(jeq + inverse[op]);  // jne, jeq, jge, jgt, jle, jlt
		label.putAdr();
	}

	//--------------- generation of the object file  ----------------

	// Writes the code buffer to the output stream
	public static void write(OutputStream s) {
		int codeSize;
		try {
			codeSize = pc;
			Decoder.decode(code, 0, codeSize - 1);
			// append header to the end of the code buffer
			put('M'); put('J');
			put4(codeSize);
			put4(dataSize);
			put4(mainPc);
			s.write(code, codeSize, pc - codeSize);	// write header
			s.write(code, 0, codeSize);							// write code
			s.close();
		} catch(IOException e) {
			error("cannot write object file");
		}
	}

	// Initializes code buffer
	static {
		code = new byte[bufSize];
		pc = 0;
		mainPc = -1;
	}
}
