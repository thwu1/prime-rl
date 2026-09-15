/* MicroJava Symbol Table - Modified with boolType, true, false (HM 23-10-02)
   ======================
------------------------------------------------------------------------*/

package MJ.SymTab;

import java.lang.*;
import MJ.*;

public class Tab {
	public static Scope curScope;	// current scope
	public static int   curLevel;	// nesting level of current scope

	public static Struct intType;	// predeclared types
	public static Struct charType;
	public static Struct nullType;
	public static Struct noType;
	public static Struct boolType;	// boolean type

	public static Obj chrObj;		  // predeclared objects
	public static Obj ordObj;
	public static Obj lenObj;
	public static Obj noObj;

	private static void error(String msg) {
		Parser.error(msg);
	}

	//------------------ scope management ---------------------

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

	//------------- Object insertion and retrieval --------------

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

	//---------------- methods for dumping the symbol table --------------

	public static void dumpStruct(Struct type) {
		String kind;
		switch (type.kind) {
			case Struct.Int:  kind = "Int  "; break;
			case Struct.Char: kind = "Char "; break;
			case Struct.Arr:  kind = "Arr  "; break;
			case Struct.Class:kind = "Class"; break;
			case Struct.Bool: kind = "Bool "; break;
			case Struct.Enum: kind = "Enum "; break;
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

	//-------------- initialization of the symbol table ------------

	static {
		curScope = new Scope();
		curScope.outer = null;
		curLevel = -1;

		// create predeclared types
		intType = new Struct(Struct.Int);
		charType = new Struct(Struct.Char);
		nullType = new Struct(Struct.Class);
		noType = new Struct(Struct.None);
		boolType = new Struct(Struct.Bool);
		noObj = new Obj(Obj.Var, "???", noType);

		// create predeclared objects
		insert(Obj.Type, "int", intType);
		insert(Obj.Type, "char", charType);
		insert(Obj.Con, "null", nullType);

		// boolean type and constants
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
