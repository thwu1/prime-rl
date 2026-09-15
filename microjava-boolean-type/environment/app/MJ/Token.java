/* MicroJava Scanner Token  (HM 23-10-02)
   =======================
----------------------------------------------------------------------*/

package MJ;

public class Token {
	public int    kind;	  // token kind
	public int    line;	  // token line (starts at 1)
	public int    col;	  // token column (starts at 1)
	public String val;	  // token value
	public int    numVal;	// numeric token value (for number and charConst)
}
