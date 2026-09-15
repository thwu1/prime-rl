/* MicroJava Type Structures - Modified with Bool and Enum kinds (HM 23-03-08)
   =========================
---------------------------------------------------------------------------*/

package MJ.SymTab;

public class Struct {
	public static final int // structure kinds
		None  = 0,
		Int   = 1,
		Char  = 2,
		Arr   = 3,
		Class = 4,
		Bool  = 5,
		Enum  = 6;
	public int    kind;		  // None, Int, Char, Arr, Class, Bool, Enum
	public Struct elemType; // for Arr: element type
	public int    nFields;  // for Class: number of fields; for Enum: number of constants
	public Obj    fields;   // for Class: fields; for Enum: constants

	public Struct(int kind) {
		this.kind = kind;
	}

	public Struct(int kind, Struct elemType) {
		this.kind = kind;
		this.elemType = elemType;
	}

	// Checks if this is a reference type
	public boolean isRefType() {
		return kind == Class || kind == Arr;
	}

	// Checks if two types are equal
	public boolean equals(Struct other) {
		if (kind == Arr)
			return other.kind == Arr && other.elemType == elemType;
		else
			return other == this;
	}

	// Checks if two types are compatible (e.g. in a comparison)
	public boolean compatibleWith(Struct other) {
		return this.equals(other)
			||	this == Tab.nullType && other.isRefType()
			||	other == Tab.nullType && this.isRefType();
	}

	// Checks if an object with type "this" can be assigned to an object with type "dest"
	public boolean assignableTo(Struct dest) {
		return this.equals(dest)
			||	this == Tab.nullType && dest.isRefType()
			||  this.kind == Arr && dest.kind == Arr && dest.elemType == Tab.noType;
	}

}
