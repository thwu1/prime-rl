/* MicroJava Labels - Modified with merge() (HM 23-10-02)
   ================
-------------------------------------------------------------------------------*/

package MJ.CodeGen;

import java.util.ArrayList;
import MJ.*;

public class Label {
	private int adr;	// adr >= 0: label address (already defined)
	                	// adr < 0:	 label still undefined
	private ArrayList<Integer> fixupList;	// list of fixup addresses to be patched

	// Creates a new undefined label
	public Label() {
		adr = -1;
		fixupList = new ArrayList<Integer>();
	}

	// Emits the jump distance to this label (if known) or 0 (and remembers fixup cell)
	public void putAdr() {
		if (adr >= 0)
			Code.put2(adr - (Code.pc-1));
		else {
			fixupList.add(Code.pc);
			Code.put2(0);
		}
	}

	// Defines the label at the current pc address and resolve fixup list
	public void here() {
		if (adr >= 0) Parser.error("label defined twice");
		for (Integer pos: fixupList) {
			Code.put2(pos, Code.pc - (pos-1));
		}
		adr = Code.pc;
	}

	// Merges another label's fixup list into this label
	public void merge(Label other) {
		this.fixupList.addAll(other.fixupList);
	}
}
