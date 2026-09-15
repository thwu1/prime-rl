#!/usr/bin/env python3
"""
Modify the MicroJava compiler to support boolean data type.
Changes: Struct.java, Tab.java, Label.java, Code.java, Parser.java
"""

import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# =============================================================================
# 1. Struct.java — add Bool kind
# =============================================================================
write_file('/app/MJ/SymTab/Struct.java', r'''/* MicroJava Type Structures (Modified for boolean support)
   =========================
-----------------------------------------------------------------------------------*/

package MJ.SymTab;

public class Struct {
	public static final int // structure kinds
		None  = 0,
		Int   = 1,
		Char  = 2,
		Arr   = 3,
		Class = 4,
		Bool  = 5;
	public int    kind;
	public Struct elemType;
	public int    nFields;
	public Obj    fields;

	public Struct(int kind) {
		this.kind = kind;
	}

	public Struct(int kind, Struct elemType) {
		this.kind = kind;
		this.elemType = elemType;
	}

	public boolean isRefType() {
		return kind == Class || kind == Arr;
	}

	public boolean equals(Struct other) {
		if (kind == Arr)
			return other.kind == Arr && other.elemType == elemType;
		else
			return other == this;
	}

	public boolean compatibleWith(Struct other) {
		return this.equals(other)
			||	this == Tab.nullType && other.isRefType()
			||	other == Tab.nullType && this.isRefType();
	}

	public boolean assignableTo(Struct dest) {
		return this.equals(dest)
			||	this == Tab.nullType && dest.isRefType()
			||  this.kind == Arr && dest.kind == Arr && dest.elemType == Tab.noType;
	}
}
''')


# =============================================================================
# 2. Tab.java — add boolType, true, false constants
# =============================================================================
write_file('/app/MJ/SymTab/Tab.java', r'''/* MicroJava Symbol Table (Modified for boolean support)
   ======================
------------------------------------------------------------------------*/

package MJ.SymTab;

import java.lang.*;
import MJ.*;

public class Tab {
	public static Scope curScope;
	public static int   curLevel;

	public static Struct intType;
	public static Struct charType;
	public static Struct nullType;
	public static Struct noType;
	public static Struct boolType;

	public static Obj chrObj;
	public static Obj ordObj;
	public static Obj lenObj;
	public static Obj noObj;

	private static void error(String msg) {
		Parser.error(msg);
	}

	public static void openScope() {
		Scope s = new Scope();
		s.outer = curScope;
		s.nVars = 0;
		curScope = s;
		curLevel++;
	}

	public static void closeScope() {
		curScope = curScope.outer;
		curLevel--;
	}

	public static Obj insert(int kind, String name, Struct type) {
		Obj obj = new Obj(kind, name, type);
		if (kind == Obj.Var) {
			obj.adr = curScope.nVars;
			curScope.nVars++;
			if (curLevel == 0 && curScope.nVars > 32768) error("too many global variables");
			else if (curLevel == 1 && curScope.nVars > 128) error("too many local variables");
			obj.level = curLevel;
		}
		Obj p = curScope.locals;
		Obj last = null;
		while (p != null) {
			if (p.name.equals(name)) error(name+" already declared");
			last = p; p = p.next;
		}
		if (last == null) curScope.locals = obj;
		else last.next = obj;
		return obj;
	}

	public static Obj find(String name) {
		for (Scope scope = curScope; scope != null; scope = scope.outer)
			for (Obj p = scope.locals; p != null; p = p.next)
				if (p.name.equals(name)) return p;
		error(name+" not found");
		return noObj;
	}

	public static Obj findField(String name, Struct type) {
		for (Obj p = type.fields; p != null; p = p.next)
			if (p.name.equals(name)) return p;
		error(name+" not found");
		return noObj;
	}

	public static void dumpStruct(Struct type) {
		String kind;
		switch (type.kind) {
			case Struct.Int:  kind = "Int  "; break;
			case Struct.Char: kind = "Char "; break;
			case Struct.Arr:  kind = "Arr  "; break;
			case Struct.Class:kind = "Class"; break;
			case Struct.Bool: kind = "Bool "; break;
			default: kind = "None";
		}
		System.out.print(kind + " ");
		if (type.kind == Struct.Arr) {
			System.out.print(" (");
			dumpStruct(type.elemType);
			System.out.print(")");
		}
		if (type.kind == Struct.Class) {
			System.out.println(type.nFields + " <<");
			for (Obj fld = type.fields; fld != null; fld = fld.next) dumpObj(fld);
			System.out.print(">>");
		}
	}

	public static void dumpObj(Obj obj) {
		String kind;
		switch (obj.kind) {
			case Obj.Con:  kind = "Con "; break;
			case Obj.Var:  kind = "Var "; break;
			case Obj.Type: kind = "Type"; break;
			case Obj.Meth: kind = "Meth"; break;
			default: kind = "None";
		}
		System.out.print(kind+" "+obj.name+" "+obj.val+" "+obj.adr+" "+obj.level+" "+obj.nPars+" (");
		dumpStruct(obj.type);
		System.out.println(")");
	}

	public static void dumpScope(Obj head) {
		System.out.println("--------------");
		for (Obj obj = head; obj != null; obj = obj.next) dumpObj(obj);
		for (Obj obj = head; obj != null; obj = obj.next)
			if (obj.kind == Obj.Meth || obj.kind == Obj.Prog) dumpScope(obj.locals);
	}

	static {
		curScope = new Scope();
		curScope.outer = null;
		curLevel = -1;

		intType = new Struct(Struct.Int);
		charType = new Struct(Struct.Char);
		nullType = new Struct(Struct.Class);
		noType = new Struct(Struct.None);
		boolType = new Struct(Struct.Bool);
		noObj = new Obj(Obj.Var, "???", noType);

		insert(Obj.Type, "int", intType);
		insert(Obj.Type, "char", charType);
		insert(Obj.Con, "null", nullType);
		insert(Obj.Type, "boolean", boolType);

		Obj trueObj = insert(Obj.Con, "true", boolType);
		trueObj.val = 1;
		Obj falseObj = insert(Obj.Con, "false", boolType);
		falseObj.val = 0;

		chrObj = insert(Obj.Meth, "chr", charType);
		chrObj.locals = new Obj(Obj.Var, "i", intType);
		chrObj.locals.level = 1;
		chrObj.nPars = 1;

		ordObj = insert(Obj.Meth, "ord", intType);
		ordObj.locals = new Obj(Obj.Var, "ch", charType);
		ordObj.locals.level = 1;
		ordObj.nPars = 1;

		lenObj = insert(Obj.Meth, "len", intType);
		lenObj.locals = new Obj(Obj.Var, "a", new Struct(Struct.Arr, noType));
		lenObj.locals.level = 1;
		lenObj.nPars = 1;
	}
}
''')


# =============================================================================
# 3. Label.java — add merge() method
# =============================================================================
write_file('/app/MJ/CodeGen/Label.java', r'''/* MicroJava Labels (Modified for boolean support)
   ================
-------------------------------------------------------------------------------*/

package MJ.CodeGen;

import java.util.ArrayList;
import MJ.*;

public class Label {
	private int adr;
	private ArrayList<Integer> fixupList;

	public Label() {
		adr = -1;
		fixupList = new ArrayList<Integer>();
	}

	public void putAdr() {
		if (adr >= 0)
			Code.put2(adr - (Code.pc-1));
		else {
			fixupList.add(Code.pc);
			Code.put2(0);
		}
	}

	// Merges another label's fixup list into this one
	public void merge(Label other) {
		this.fixupList.addAll(other.fixupList);
	}

	public void here() {
		if (adr >= 0) Parser.error("label defined twice");
		for (Integer pos: fixupList) {
			Code.put2(pos, Code.pc - (pos-1));
		}
		adr = Code.pc;
	}
}
''')


# =============================================================================
# 4. Code.java — add Cond-to-value conversion in load()
# =============================================================================
write_file('/app/MJ/CodeGen/Code.java', r'''/* MicroJava Code Generator (Modified for boolean support)
   ========================
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
		trap        = 57;

	public static final int  // compare operators
		eq = 0,
		ne = 1,
		lt = 2,
		le = 3,
		gt = 4,
		ge = 5;

	private static int[] inverse = {ne, eq, ge, gt, le, lt};
	private static final int bufSize = 8192;

	private static byte[] code;
	public static int pc;
	public static int mainPc;
	public static int dataSize;

	private static void error(String msg) {
		Parser.error(msg);
	}

	public static void put(int x) {
		if (pc >= bufSize) {
			if (pc == bufSize) error("program too large");
			pc++;
		} else
			code[pc++] = (byte)x;
	}

	public static void put2(int x) {
		put(x>>8); put(x);
	}

	public static void put2(int pos, int x) {
		int oldpc = pc; pc = pos; put2(x); pc = oldpc;
	}

	public static void put4(int x) {
		put2(x>>16); put2(x);
	}

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
			case Operand.Stack:
				break;
			case Operand.Cond: {
				// Convert Cond to value: 1 (true) or 0 (false)
				fJump(x.op, x.fLabel);
				x.tLabel.here();
				put(const1);
				Label end = new Label();
				jump(end);
				x.fLabel.here();
				put(const0);
				end.here();
				x.type = Tab.boolType;
				break;
			}
			case Operand.Meth:
				error("cannot load this");
				break;
		}
		x.kind = Operand.Stack;
	}

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

	public static void callMethod (Operand m) {
		if (m.obj == Tab.ordObj || m.obj == Tab.chrObj) ;
		else if (m.obj == Tab.lenObj)
			put(arraylength);
		else {
			put(call); put2(m.adr - (pc - 1));
		}
	}

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
				put(aload);
				if (val == 1) put(const1); else put(const_m1);
				put(add);
				put(astore);
				break;
			default:
				error("++ or -- not applicable");
				break;
		}
	}

	public static void jump(Label lab) {
		put(jmp); lab.putAdr();
	}

	public static void tJump (int op, Label label) {
		put(jeq + op);
		label.putAdr();
	}

	public static void fJump (int op, Label label) {
		put(jeq + inverse[op]);
		label.putAdr();
	}

	public static void write(OutputStream s) {
		int codeSize;
		try {
			codeSize = pc;
			Decoder.decode(code, 0, codeSize - 1);
			put('M'); put('J');
			put4(codeSize);
			put4(dataSize);
			put4(mainPc);
			s.write(code, codeSize, pc - codeSize);
			s.write(code, 0, codeSize);
			s.close();
		} catch(IOException e) {
			error("cannot write object file");
		}
	}

	static {
		code = new byte[bufSize];
		pc = 0;
		mainPc = -1;
	}
}
''')


# =============================================================================
# 5. Parser.java — restructured grammar with boolean support
# =============================================================================
write_file('/app/MJ/Parser.java', r'''/*  MicroJava Parser (Modified for boolean support)
    ================
    Grammar restructured: Expr/Term/Factor now handle boolean operators.
    Old Expr/Term/Factor renamed to SimpleExpr/SimpleTerm/SimpleFactor.
    Condition/CondTerm/CondFactor removed.
---------------------------------------------------------------------------*/

package MJ;

import java.util.*;
import MJ.SymTab.*;
import MJ.CodeGen.*;

public class Parser {
	private static final int  // token codes
		none      = 0,
		ident     = 1,
		number    = 2,
		charCon   = 3,
		plus      = 4,
		minus     = 5,
		times     = 6,
		slash     = 7,
		rem       = 8,
		pplus     = 9,
		mminus    = 10,
		eql       = 11,
		neq       = 12,
		lss       = 13,
		leq       = 14,
		gtr       = 15,
		geq       = 16,
		and       = 17,
		or        = 18,
		lpar      = 19,
		rpar      = 20,
		lbrack    = 21,
		rbrack    = 22,
		lbrace    = 23,
		rbrace    = 24,
		assign    = 25,
		semicolon = 26,
		comma     = 27,
		period    = 28,
		break_    = 29,
		class_    = 30,
		else_     = 31,
		final_    = 32,
		if_       = 33,
		new_      = 34,
		print_    = 35,
		program_  = 36,
		read_     = 37,
		return_   = 38,
		void_     = 39,
		while_    = 40,
		eof       = 41;

	private static final String[] name = {
		"none", "identifier", "number", "char constant", "+", "-", "*", "/", "%",
		"++", "--", "==", "!=", "<", "<=", ">", ">=", "&&", "||",
		"(", ")", "[", "]", "{", "}", "=", ";", ",", ".",
		"break", "class", "else", "final", "if", "new", "print",
		"program", "read", "return", "void", "while", "eof"
	};

	private static Token t;
	private static Token la;
	private static int sym;
	public  static int errors;
	private static int errDist;

	private static Obj   curMethod;
	private static Label breakLab = null;
	private static Stack<Label> breakLabStack = new Stack<Label>();

	private static BitSet firstExpr, firstStat, syncStat, syncDecl;

	private static void scan() {
		t = la;
		la = Scanner.next();
		sym = la.kind;
		errDist++;
	}

	private static void check(int expected) {
		if (sym == expected) scan();
		else error(name[expected] + " expected");
	}

	public static void error(String msg) {
		if (errDist >= 3) {
			System.out.println("-- line " + la.line + " col " + la.col + ": " + msg);
			errors++;
		}
		errDist = 0;
	}

	// Converts an operand to a Cond operand if necessary.
	// Only boolean variables/constants can be converted.
	private static Operand makeCond(Operand x) {
		if (x.kind == Operand.Cond) return x;
		if (x.type == Tab.boolType) {
			Code.load(x);
			Code.put(Code.const1); // compare with true
		} else {
			error("boolean expected");
		}
		return new Operand(Operand.Cond, Code.eq, Tab.boolType);
	}

	// ActPars = '(' [Expr {',' Expr}] ')'.
	private static void ActPars(Operand m) {
		if (m.kind != Operand.Meth) {
			error("called object is not a method");
			m.obj = Tab.noObj;
		}
		scan();
		int aPars = 0;
		int fPars = m.obj.nPars;
		if (firstExpr.get(sym)) {
			Obj fp = m.obj.locals;
			for (;;) {
				Operand ap = Expr();
				Code.load(ap);
				aPars++;
				if (fp != null) {
					if (!ap.type.assignableTo(fp.type)) error("parameter type mismatch");
					fp = fp.next;
				}
				if (sym == comma) scan(); else break;
			}
		}
		check(rpar);
		if (m.kind == Operand.Meth) {
			if (aPars > fPars) error("more actual than formal parameters");
			else if (aPars < fPars) error("fewer actual than formal parameters");
		}
	}

	// Block = '{' {Statement} '}'.
	private static void Block() {
		check(lbrace);
		while (sym != rbrace && sym != eof) {
			Statement();
		}
		check(rbrace);
	}

	// ClassDecl = "class" ident '{' {VarDecl} '}'.
	private static void ClassDecl() {
		scan();
		check(ident);
		Obj obj = Tab.insert(Obj.Type, t.val, new Struct(Struct.Class));
		check(lbrace);
		Tab.openScope();
		while (sym == ident) VarDecl();
		check(rbrace);
		obj.type.nFields = Tab.curScope.nVars;
		obj.type.fields = Tab.curScope.locals;
		Tab.closeScope();
	}

	// ConstDecl = "final" Type ident '=' (number | charCon) ';'.
	private static void ConstDecl() {
		scan();
		Struct type = Type();
		check(ident);
		Obj obj = Tab.insert(Obj.Con, t.val, type);
		check(assign);
		if (sym == number) {
			scan();
			obj.val = t.numVal;
			if (type != Tab.intType) error("value does not match constant type");
		} else if (sym == charCon) {
			scan();
			obj.val = t.numVal;
			if (type != Tab.charType) error("value does not match constant type");
		} else error("constant expected");
		check(semicolon);
	}

	// Designator = ident {'.' ident | '[' Expr ']'}.
	private static Operand Designator() {
		check(ident);
		Operand x = new Operand(Tab.find(t.val));
		for (;;) {
			if (sym == period) {
				Code.load(x);
				scan();
				check(ident);
				if (x.type.kind == Struct.Class) {
					Obj fld = Tab.findField(t.val, x.type);
					x.adr = fld.adr;
					x.type = fld.type;
				} else error("dereferenced object is not a class");
				x.kind = Operand.Fld;
			} else if (sym == lbrack) {
				Code.load(x);
				scan();
				Operand y = Expr();
				check(rbrack);
				if (x.type.kind == Struct.Arr) {
					if (y.type != Tab.intType) error("index must be of type int");
					Code.load(y);
					x.type = x.type.elemType;
				} else error("indexed object is not an array");
				x.kind = Operand.Elem;
			} else break;
		}
		return x;
	}

	// ======== New grammar with boolean support ========

	// Expr = Term {"||" Term}.
	private static Operand Expr() {
		Operand x = Term();
		while (sym == or) {
			scan();
			x = makeCond(x);
			Code.tJump(x.op, x.tLabel);
			x.fLabel.here();
			Operand y = Term();
			y = makeCond(y);
			x.op = y.op;
			x.fLabel = y.fLabel;
			x.tLabel.merge(y.tLabel);
		}
		return x;
	}

	// Term = Factor {"&&" Factor}.
	private static Operand Term() {
		Operand x = Factor();
		while (sym == and) {
			scan();
			x = makeCond(x);
			Code.fJump(x.op, x.fLabel);
			x.tLabel.here();
			Operand y = Factor();
			y = makeCond(y);
			x.op = y.op;
			x.tLabel = y.tLabel;
			x.fLabel.merge(y.fLabel);
		}
		return x;
	}

	// Factor = SimpleExpr [Relop SimpleExpr].
	private static Operand Factor() {
		Operand x = SimpleExpr();
		if (sym == eql || sym == neq || sym == lss || sym == leq || sym == gtr || sym == geq) {
			Code.load(x);
			int op = Relop();
			Operand y = SimpleExpr();
			Code.load(y);
			if (!x.type.compatibleWith(y.type)) error("type mismatch");
			if (x.type.isRefType() && op != Code.eq && op != Code.ne) error("invalid compare");
			x = new Operand(Operand.Cond, op, Tab.boolType);
		}
		return x;
	}

	// SimpleExpr = ['-'] SimpleTerm {('+' | '-') SimpleTerm}.
	private static Operand SimpleExpr() {
		Operand x;
		if (sym == minus) {
			scan();
			x = SimpleTerm();
			if (x.type != Tab.intType) error("integer operand required");
			if (x.kind == Operand.Con)
				x.val = - x.val;
			else {
				Code.load(x);
				Code.put(Code.neg);
			}
		} else {
			x = SimpleTerm();
		}
		while (sym == plus || sym == minus) {
			int op = sym == plus ? Code.add : Code.sub;
			scan();
			Code.load(x);
			Operand y = SimpleTerm();
			Code.load(y);
			if (x.type != Tab.intType || y.type != Tab.intType)
				error("operands must be of type int");
			Code.put(op);
		}
		return x;
	}

	// SimpleTerm = SimpleFactor {('*' | '/' | '%') SimpleFactor}.
	private static Operand SimpleTerm() {
		Operand x = SimpleFactor();
		while (sym == times || sym == slash || sym == rem) {
			int op = Code.mul + (sym - times);
			scan();
			Code.load(x);
			Operand y = SimpleFactor();
			Code.load(y);
			if (x.type != Tab.intType || y.type != Tab.intType)
				error("operands must be of type int");
			Code.put(op);
		}
		return x;
	}

	// SimpleFactor = Designator [ActPars] | number | charCon | "new" ident ['[' Expr ']'] | '(' Expr ')'.
	private static Operand SimpleFactor() {
		Operand x;
		if (sym == ident) {
			x = Designator();
			if (sym == lpar) {
				ActPars(x);
				if (x.type == Tab.noType) error("void method called as a function");
				Code.callMethod(x);
				x.kind = Operand.Stack;
			}
		} else if (sym == number) {
			scan();
			x = new Operand(t.numVal);
		} else if (sym == charCon) {
			scan();
			x = new Operand(t.numVal);
			x.type = Tab.charType;
		} else if (sym == new_) {
			scan();
			check(ident);
			Obj obj = Tab.find(t.val);
			Struct type = obj.type;
			if (sym == lbrack) {
				if (obj.kind != Obj.Type) error("type expected");
				scan();
				x = Expr();
				if (x.type != Tab.intType) error("array size must be of type integer");
				Code.load(x);
				Code.put(Code.newarray);
				if (type == Tab.charType) Code.put(0); else Code.put(1);
				check(rbrack);
				type = new Struct(Struct.Arr, type);
			} else {
				if (obj.kind != Obj.Type || type.kind != Struct.Class) error("class type expected");
				Code.put(Code.new_); Code.put2(type.nFields);
			}
			x = new Operand(Operand.Stack, 0, type);
		} else if (sym == lpar) {
			scan();
			x = Expr();
			check(rpar);
		} else {
			error("invalid expression");
			x = new Operand(Operand.Stack, 0, Tab.intType);
		}
		return x;
	}

	// FormPar = Type ident.
	private static void FormPar() {
		Struct type = Type();
		check(ident);
		Tab.insert(Obj.Var, t.val, type);
	}

	// FormPars = FormPar {',' FormPar}.
	private static int FormPars() {
		int n = 0;
		FormPar(); n++;
		while (sym == comma) {
			scan();
			FormPar(); n++;
		}
		return n;
	}

	// MethodDecl = (Type | "void") ident '(' [FormPars] ')' {VarDecl} Block.
	private static void MethodDecl() {
		Struct type = Tab.noType;
		if (sym == ident) {
			type = Type();
			if (type.isRefType()) error("methods may only return int, char, or boolean");
		} else if (sym == void_) {
			scan();
		} else error("function type or void expected");
		check(ident);
		String methName = t.val;
		curMethod = Tab.insert(Obj.Meth, methName, type);
		Tab.openScope();
		check(lpar);
		if (sym == ident) curMethod.nPars = FormPars();
		if (methName.equals("main")) {
			Code.mainPc = Code.pc;
			if (curMethod.type != Tab.noType) error("main method must be void");
			if (curMethod.nPars != 0) error("main method must not have parameters");
		}
		check(rpar);
		while (sym == ident) VarDecl();
		curMethod.locals = Tab.curScope.locals;
		curMethod.adr = Code.pc;
		Code.put(Code.enter); Code.put(curMethod.nPars); Code.put(Tab.curScope.nVars);
		Block();
		if (curMethod.type == Tab.noType) {
			Code.put(Code.exit);
			Code.put(Code.return_);
		} else {
			Code.put(Code.trap);
			Code.put(1);
		}
		Tab.closeScope();
	}

	// Program = "program" ident {ConstDecl | ClassDecl | VarDecl} '{' {MethodDecl} '}'.
	private static void Program() {
		check(program_);
		check(ident);
		Obj prog = Tab.insert(Obj.Prog, t.val, Tab.noType);
		Tab.openScope();
		while (sym != lbrace && sym != void_ && sym != eof) {
			if (sym == final_) ConstDecl();
			else if (sym == class_) ClassDecl();
			else if (sym == ident) VarDecl();
			else {
				error("invalid declaration");
				while (!syncDecl.get(sym)) scan();
				errDist = 0;
			}
		}
		check(lbrace);
		while (sym == ident || sym == void_) MethodDecl();
		check(rbrace);
		prog.locals = Tab.curScope.locals;
		Code.dataSize = Tab.curScope.nVars;
		Tab.closeScope();
	}

	// Relop = "==" | "!=" | '>' | ">=" | '<' | "<=".
	private static int Relop() {
		if (sym == eql) {scan(); return Code.eq;}
		else if (sym == neq) {scan(); return Code.ne;}
		else if (sym == gtr) {scan(); return Code.gt;}
		else if (sym == geq) {scan(); return Code.ge;}
		else if (sym == lss) {scan(); return Code.lt;}
		else if (sym == leq) {scan(); return Code.le;}
		else {error("relational operator expected"); return Code.eq;}
	}

	// Statement = ...
	private static void Statement() {
		Operand x, y;

		if (!firstStat.get(sym)) {
			error("invalid start of statement");
			while (!syncStat.get(sym)) scan();
			errDist = 0;
		}

		// Designator ('=' Expr | ActPars | "++" | "--") ';'
		if (sym == ident) {
			x = Designator();
			if (sym == assign) {
				scan();
				y = Expr();
				if (y.type.assignableTo(x.type)) {
					Code.load(y);
					Code.assignTo(x);
				} else {
					error("incompatible types in assignment");
				}
			} else if (sym == lpar) {
				ActPars(x);
				Code.callMethod(x);
				if (x.type != Tab.noType) Code.put(Code.pop);
			} else if (sym == pplus) {
				scan();
				Code.inc(x, 1);
			} else if (sym == mminus) {
				scan();
				Code.inc(x, -1);
			} else error("invalid assignment or call");
			check(semicolon);

		// "if" '(' Expr ')' Statement ["else" Statement]
		} else if (sym == if_) {
			scan();
			check(lpar);
			x = Expr();
			x = makeCond(x);
			check(rpar);
			Code.fJump(x.op, x.fLabel);
			x.tLabel.here();
			Statement();
			if (sym == else_) {
				scan();
				Label end = new Label();
				Code.jump(end);
				x.fLabel.here();
				Statement();
				end.here();
			} else {
				x.fLabel.here();
			}

		// "while" '(' Expr ')' Statement
		} else if (sym == while_) {
			scan();
			breakLabStack.push(breakLab);
			breakLab = new Label();
			Label top = new Label(); top.here();
			check(lpar);
			x = Expr();
			x = makeCond(x);
			check(rpar);
			Code.fJump(x.op, x.fLabel);
			x.tLabel.here();
			Statement();
			Code.jump(top);
			x.fLabel.here();
			breakLab.here();
			breakLab = breakLabStack.pop();

		// "break" ";"
		} else if (sym == break_) {
			scan();
			if (breakLab != null) Code.jump(breakLab); else error("break outside a loop");
			check(semicolon);

		// "return" [Expr] ';'
		} else if (sym == return_) {
			scan();
			if (firstExpr.get(sym)) {
				x = Expr();
				Code.load(x);
				if (curMethod.type == Tab.noType) error("void method must not return a value");
				else if (!x.type.assignableTo(curMethod.type)) error("return type must match method type");
			} else if (curMethod.type != Tab.noType) {
				error("return expression expected");
			}
			Code.put(Code.exit);
			Code.put(Code.return_);
			check(semicolon);

		// "read" '(' Designator ')' ';'
		} else if (sym == read_) {
			scan();
			check(lpar);
			x = Designator();
			check(rpar);
			if (x.type == Tab.intType) Code.put(Code.read);
			else if (x.type == Tab.charType) Code.put(Code.bread);
			else error("can only read int or char variables");
			Code.assignTo(x);
			check(semicolon);

		// "print" '(' Expr [',' number] ')' ';'
		} else if (sym == print_) {
			scan();
			check(lpar);
			x = Expr();
			Code.load(x);
			if (sym == comma) {
				scan();
				check(number);
				y = new Operand(t.numVal);
			} else {
				y = new Operand(0);
			}
			Code.load(y);
			if (x.type == Tab.intType) Code.put(Code.print);
			else if (x.type == Tab.charType) Code.put(Code.bprint);
			else if (x.type == Tab.boolType) Code.put(Code.print);
			else error("can only print int, char, or boolean values");
			check(rpar);
			check(semicolon);

		// Block
		} else if (sym == lbrace) {
			Block();

		// ';'
		} else if (sym == semicolon) {
			scan();
		} else {
			error("compiler error in statement");
		}
	}

	// Type = ident ['[' ']'].
	private static Struct Type() {
		check(ident);
		Obj obj = Tab.find(t.val);
		if (obj.kind != Obj.Type) error("type expected");
		Struct type = obj.type;
		if (sym == lbrack) {
			type = new Struct(Struct.Arr, type);
			scan();
			check(rbrack);
		}
		return type;
	}

	// VarDecl = Type ident {',' ident} ';'.
	private static void VarDecl() {
		Struct type = Type();
		check(ident);
		Tab.insert(Obj.Var, t.val, type);
		while (sym == comma) {
			scan();
			check(ident);
			Tab.insert(Obj.Var, t.val, type);
		}
		check(semicolon);
	}

	public static void parse() {
		BitSet s;
		s = new BitSet(64); firstExpr = s;
		s.set(ident); s.set(number); s.set(charCon); s.set(new_); s.set(lpar); s.set(minus);

		s = new BitSet(64); firstStat = s;
		s.set(ident); s.set(if_); s.set(while_); s.set(break_); s.set(read_);
		s.set(return_); s.set(print_); s.set(lbrace); s.set(semicolon);

		s = (BitSet)firstStat.clone(); syncStat = s;
		s.clear(ident); s.set(rbrace); s.set(eof);

		s = new BitSet(64); syncDecl = s;
		s.set(final_); s.set(ident); s.set(class_); s.set(lbrace); s.set(void_); s.set(eof);

		errors = 0;
		errDist = 3;
		scan();
		Program();
		if (sym != eof) error("end of file found before end of program");
		if (Code.mainPc < 0) error("program contains no 'main' method");
	}
}
''')

print("All compiler modifications applied successfully.")
