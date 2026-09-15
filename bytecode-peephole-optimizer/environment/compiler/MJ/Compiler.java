/* MicroJava Main Class  (HM 23-10-02)
   ====================
   This is the main class of the MicroJava compiler. It initializes the Scanner
   and calls the Parser, which directs the compilation.

   Synopsis: java MJ.Compiler <sourceFileName>

   The output is written to a file <sourceFileName>.obj.
------------------------------------------------------------------------------*/

package MJ;

import java.io.*;
import MJ.CodeGen.*;

public class Compiler {

	private static String changeExtension(String s) {
		int i = s.lastIndexOf('.');
		if (i < 0) return s + ".obj"; else return s.substring(0, i) + ".obj";
	}

	// Main method of the MicroJava compiler
	public static void main(String args[]) {
		if (args.length > 0) {
			String sourceFileName = args[0];
			String outputFileName = changeExtension(sourceFileName);
			try {
				Scanner.init(new InputStreamReader(new FileInputStream(sourceFileName)));
				Parser.parse();
				if (Parser.errors == 0) {
					try {
						Code.write(new FileOutputStream(outputFileName));
					} catch (IOException e) {
						System.out.println("-- cannot open output file " + outputFileName);
					}
				}
			} catch (IOException e) {
				System.out.println("-- cannot open input file " + sourceFileName);
			}
		} else System.out.println("-- synopsis: java MJ.Compiler <sourceFileName>");
	}

}