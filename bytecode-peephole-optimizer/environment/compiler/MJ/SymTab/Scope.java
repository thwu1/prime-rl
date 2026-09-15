/* MicroJava Symbol Table Scopes (HM 23-10-02)
   =============================
   This is the header node of a scope. It links this scope
   to its outer scope and to its local objects.
-----------------------------------------------------------*/

package MJ.SymTab;

public class Scope {
	public Scope outer;		// to outer scope
	public Obj   locals;	// to local objects of this scope
	public int   nVars;   // number of variables in this scope
}