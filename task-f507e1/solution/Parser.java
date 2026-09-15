/*  MicroJava Parser - Modified with boolean and enum extensions (HM 23-10-02)
    ================
---------------------------------------------------------------------------*/

package MJ;

import java.util.*;
import MJ.SymTab.*;
import MJ.CodeGen.*;

public class Parser {
	private static final int  // token codes
		none      = 0,  // error token
		ident     = 1,  // identifier
		number    = 2,  // number
		charCon   = 3,  // character constant
		plus      = 4,  // +
		minus     = 5,  // -
		times     = 6,  // *
		slash     = 7,  // /
		rem       = 8,  // %
		pplus     = 9,  // ++
		mminus    = 10, // --
		eql       = 11, // ==
		neq       = 12, // !=
		lss       = 13, // <
		leq       = 14, // <=
		gtr       = 15, // >
		geq       = 16, // >=
		and       = 17, // &&
		or        = 18, // ||
		lpar      = 19, // (
		rpar      = 20, // )
		lbrack    = 21, // [
		rbrack    = 22, // ]
		lbrace    = 23, // {
		rbrace    = 24, // }
		assign    = 25, // =
		semicolon = 26, // ;
		comma     = 27, // ,
		period    = 28, // .
		break_    = 29, // ... keywords ...
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
		enum_     = 41, // enum keyword
		eof       = 42; // end-of-file token

	private static final String[] name = { // token names for error messages
		"none", "identifier", "number", "char constant", "+", "-", "*", "/", "%",
		"++", "--", "==", "!=", "<", "<=", ">", ">=", "&&", "||",
		"(", ")", "[", "]", "{", "}", "=", ";", ",", ".",
		"break", "class", "else", "final", "if", "new", "print",
		"program", "read", "return", "void", "while", "enum", "eof"
	};

	private static Token t;				// most recently recognized token
	private static Token la;			// lookahead token (not yet processed)
	private static int sym;				// contains la.kind
	public  static int errors;  	// error counter
	private static int errDist;		// number of correctly parsed tokens since the last error

	private static Obj   curMethod;	      // currently compiled method

	private static Label breakLab = null;
	private static Stack<Label> breakLabStack = new Stack<Label>();

	//----------- terminal first/sync sets; initialized in method parse() -----
	private static BitSet firstExpr, firstStat, syncStat, syncDecl;


	//------------------------ auxiliary methods ---------------------------

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

	// Converts an operand to a Cond operand (for use in conditions)
	private static Operand makeCond(Operand x) {
		if (x.kind == Operand.Cond) return x;
		if (x.type == Tab.boolType) {
			Code.load(x);
			Code.put(Code.const1); // push true (1)
		} else {
			error("boolean expected");
		}
		return new Operand(Operand.Cond, Code.eq, Tab.boolType);
	}

	//-------------- parsing methods (in alphabetical order) -----------------

	// ActPars = '(' [Expr {',' Expr}] ')'.
	private static void ActPars(Operand m) {
		if (m.kind != Operand.Meth) {
			error("called object is not a method");
			m.obj = Tab.noObj;
		}
		scan(); // lpar
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
		scan(); // class
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
		scan(); // final
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
				if (x.kind == Operand.Type) {
					// Enum constant access: EnumType.CONSTANT
					scan();
					check(ident);
					if (x.type.kind == Struct.Enum) {
						Obj con = Tab.findField(t.val, x.type);
						x.kind = Operand.Con;
						x.val = con.val;
						x.type = con.type;
					} else {
						error("enum type expected");
					}
				} else {
					// Class field access
					Code.load(x);
					scan();
					check(ident);
					if (x.type.kind == Struct.Class) {
						Obj fld = Tab.findField(t.val, x.type);
						x.adr = fld.adr;
						x.type = fld.type;
					} else error("dereferenced object is not a class");
					x.kind = Operand.Fld;
				}
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

	// EnumDecl = "enum" ident '{' ident {',' ident} '}'.
	private static void EnumDecl() {
		scan(); // enum
		check(ident);
		Struct type = new Struct(Struct.Enum);
		Tab.insert(Obj.Type, t.val, type);
		Tab.openScope();
		int val = 0;
		check(lbrace);
		check(ident);
		Obj obj = Tab.insert(Obj.Con, t.val, type);
		obj.val = val; val++;
		while (sym == comma) {
			scan();
			check(ident);
			obj = Tab.insert(Obj.Con, t.val, type);
			obj.val = val; val++;
		}
		check(rbrace);
		type.nFields = val;
		type.fields = Tab.curScope.locals;
		Tab.closeScope();
	}

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
			if (type.isRefType()) error("methods may only return int or char");
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

	// Program = "program" ident {ConstDecl | ClassDecl | EnumDecl | VarDecl} '{' {MethodDecl} '}'.
	private static void Program() {
		check(program_);
		check(ident);
		Obj prog = Tab.insert(Obj.Prog, t.val, Tab.noType);
		Tab.openScope();
		while (sym != lbrace && sym != void_ && sym != eof) {
			if (sym == final_) ConstDecl();
			else if (sym == class_) ClassDecl();
			else if (sym == enum_) EnumDecl();
			else if (sym == ident) VarDecl();
			else { // error => recover
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

	// SimpleTerm = SimpleFactor {('*' | '/' | '%') SimpleFactor}
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

	// Statement = ...
	private static void Statement() {
		Operand x, y; int op, adr, adr2;

		// error check and recovery
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
			else if (x.type.kind == Struct.Enum) Code.put(Code.print);
			else error("can only print int, char, boolean, or enum values");
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

	// Main method; starts the parser
	public static void parse() {
		BitSet s;
		// initialize first/sync sets
		s = new BitSet(64); firstExpr = s;
		s.set(ident); s.set(number); s.set(charCon); s.set(new_); s.set(lpar); s.set(minus);

		s = new BitSet(64); firstStat = s;
		s.set(ident); s.set(if_); s.set(while_); s.set(break_); s.set(read_);
		s.set(return_); s.set(print_); s.set(lbrace); s.set(semicolon);

		s = (BitSet)firstStat.clone(); syncStat = s;
		s.clear(ident); s.set(rbrace); s.set(eof);

		s = new BitSet(64); syncDecl = s;
		s.set(final_); s.set(ident); s.set(class_); s.set(enum_); s.set(lbrace); s.set(void_); s.set(eof);

		// start parsing
		errors = 0;
		errDist = 3;
		scan();
		Program();
		if (sym != eof) error("end of file found before end of program");
		if (Code.mainPc < 0) error("program contains no 'main' method");
	}

}
