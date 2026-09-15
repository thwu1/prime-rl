/* MicroJava Code Operands - Modified with Type kind (HM 23-10-02)
   =======================
----------------------------------------------------------------------*/

package MJ.CodeGen;

import MJ.*;
import MJ.SymTab.*;

public class Operand {
	public static final int  // operand kinds
	  Con    = 0,
	  Local  = 1,
	  Static = 2,
	  Stack  = 3,
	  Fld    = 4,
	  Elem   = 5,
	  Meth   = 6,
	  Cond   = 7,
	  Type   = 8;   // type reference (for enum constant access)

	public int    kind;	  // Con, Local, Static, Stack, Fld, Elem, Meth, Cond, Type
	public Struct type;	  // operand type
	public Obj    obj;    // Meth: method object
	public int    val;    // Con: constant value
	public int    adr;    // Local, Static, Fld, Meth: address
	public int    op;     // Cond: most recent compare operator
	public Label  tLabel; // Cond: label (fixup list) for true-jumps
	public Label  fLabel; // Cond: label (fixup list) for false-jumps

	public Operand(Obj obj) {
		type = obj.type; val = obj.val; adr = obj.adr; kind = Stack; // default
		switch (obj.kind) {
			case Obj.Con:
				kind = Con; break;
			case Obj.Var:
				if (obj.level == 0) kind = Static; else kind = Local;
				break;
			case Obj.Meth:
				kind = Meth; this.obj = obj; break;
			case Obj.Type:
				kind = Type; break;
			case Obj.Prog:
				Parser.error("the program cannot be used as an operand"); break;
		}
	}

	public Operand(int val) {
		kind = Con; this.val = val; type = Tab.intType;
	}

	public Operand(int kind, int val, Struct type) {
		this.kind = kind; this.val = val; this.type = type;
		if (kind == Cond) {
			op = val;             // most recent compare operator
			tLabel = new Label(); // labels are still unused
			fLabel = new Label();
		}
	}

}
