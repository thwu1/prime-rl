#!/usr/bin/env python3
"""
Patch the MicroJava compiler to add boolean data type support.

Modifies: Struct.java, Tab.java, Label.java, Code.java, Parser.java
"""

import os

COMPILER_BASE = "/app/Compiler/MJ"


def read_file(path):
    with open(path, "r") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)
    print(f"  Patched {path}")


# ============================================================
# 1. Struct.java  -  Add Bool kind
# ============================================================
def patch_struct():
    path = os.path.join(COMPILER_BASE, "SymTab", "Struct.java")
    src = read_file(path)
    src = src.replace(
        "Arr   = 3,\n\t\tClass = 4;",
        "Arr   = 3,\n\t\tClass = 4,\n\t\tBool  = 5;"
    )
    write_file(path, src)


# ============================================================
# 2. Tab.java  -  Add boolType and true/false constants
# ============================================================
def patch_tab():
    path = os.path.join(COMPILER_BASE, "SymTab", "Tab.java")
    src = read_file(path)

    # Add boolType declaration alongside other type declarations
    src = src.replace(
        "public static Struct nullType;\n\tpublic static Struct noType;",
        "public static Struct nullType;\n\tpublic static Struct noType;\n\tpublic static Struct boolType;"
    )

    # Add boolType creation in static initializer
    src = src.replace(
        "nullType = new Struct(Struct.Class);\n\t\tnoType = new Struct(Struct.None);",
        "nullType = new Struct(Struct.Class);\n\t\tnoType = new Struct(Struct.None);\n\t\tboolType = new Struct(Struct.Bool);"
    )

    # Add boolean type and true/false constants to universe
    # Insert after the null constant declaration
    src = src.replace(
        'insert(Obj.Con, "null", nullType);',
        'insert(Obj.Con, "null", nullType);\n\n'
        '\t\tinsert(Obj.Type, "boolean", boolType);\n'
        '\t\tObj trueObj = insert(Obj.Con, "true", boolType);\n'
        '\t\ttrueObj.val = 1;\n'
        '\t\tObj falseObj = insert(Obj.Con, "false", boolType);\n'
        '\t\tfalseObj.val = 0;'
    )

    write_file(path, src)


# ============================================================
# 3. Label.java  -  Add merge() method
# ============================================================
def patch_label():
    path = os.path.join(COMPILER_BASE, "CodeGen", "Label.java")
    src = read_file(path)

    # Add merge method before the closing brace of the class
    merge_method = (
        "\n\n\t// Merges another label's fixup list into this one\n"
        "\tpublic void merge(Label other) {\n"
        "\t\tthis.fixupList.addAll(other.fixupList);\n"
        "\t}\n"
    )
    # Insert before the final closing brace
    last_brace = src.rfind("}")
    src = src[:last_brace] + merge_method + src[last_brace:]

    write_file(path, src)


# ============================================================
# 4. Code.java  -  Add Cond-to-value conversion in load()
# ============================================================
def patch_code():
    path = os.path.join(COMPILER_BASE, "CodeGen", "Code.java")
    src = read_file(path)

    # Replace the error case for Cond with actual conversion code
    old_cond = (
        "case Operand.Meth: // should never happen\n"
        "\t\t\tcase Operand.Cond:\n"
        "\t\t\t\terror(\"cannot load this\");\n"
        "\t\t\t\tbreak;"
    )
    new_cond = (
        "case Operand.Meth:\n"
        "\t\t\t\terror(\"cannot load this\");\n"
        "\t\t\t\tbreak;\n"
        "\t\t\tcase Operand.Cond:\n"
        "\t\t\t\tfJump(x.op, x.fLabel);\n"
        "\t\t\t\tx.tLabel.here();\n"
        "\t\t\t\tput(const1);\n"
        "\t\t\t\tLabel end = new Label();\n"
        "\t\t\t\tjump(end);\n"
        "\t\t\t\tx.fLabel.here();\n"
        "\t\t\t\tput(const0);\n"
        "\t\t\t\tend.here();\n"
        "\t\t\t\tx.type = Tab.boolType;\n"
        "\t\t\t\tbreak;"
    )
    src = src.replace(old_cond, new_cond)

    write_file(path, src)


# ============================================================
# 5. Parser.java  -  Major grammar restructuring
# ============================================================
def patch_parser():
    path = os.path.join(COMPILER_BASE, "Parser.java")
    src = read_file(path)

    # --- Step 1: Remove Condition, CondFactor, CondTerm methods ---

    # Remove Condition method
    cond_start = src.find("\t// Condition = CondTerm")
    cond_method_end = src.find("\treturn x;\n\t}\n", cond_start)
    cond_block_end = cond_method_end + len("\treturn x;\n\t}\n")
    src = src[:cond_start] + src[cond_block_end:]

    # Remove CondFactor method
    cf_start = src.find("\t// CondFactor = Expr Relop Expr")
    cf_method_end = src.find("\treturn x;\n\t}\n", cf_start)
    cf_block_end = cf_method_end + len("\treturn x;\n\t}\n")
    src = src[:cf_start] + src[cf_block_end:]

    # Remove CondTerm method
    ct_start = src.find("\t// CondTerm = CondFactor")
    ct_method_end = src.find("\treturn x;\n\t}\n", ct_start)
    ct_block_end = ct_method_end + len("\treturn x;\n\t}\n")
    src = src[:ct_start] + src[ct_block_end:]

    # --- Step 2: Rename internal calls before renaming methods ---
    # Term(); -> SimpleTerm();  (only in old Expr body)
    src = src.replace("Term();", "SimpleTerm();")
    # Factor(); -> SimpleFactor();  (only in old Term body)
    src = src.replace("Factor();", "SimpleFactor();")

    # --- Step 3: Rename method definitions ---
    src = src.replace(
        "// Expr = ['-'] Term {('+' | '-') Term}.",
        "// SimpleExpr = ['-'] SimpleTerm {('+' | '-') SimpleTerm}."
    )
    src = src.replace(
        "private static Operand Expr() {",
        "private static Operand SimpleExpr() {"
    )

    src = src.replace(
        "// Term = Factor {('*' | '/' | '%') Factor}",
        "// SimpleTerm = SimpleFactor {('*' | '/' | '%') SimpleFactor}"
    )
    src = src.replace(
        "private static Operand Term() {",
        "private static Operand SimpleTerm() {"
    )

    src = src.replace(
        "// Factor = Designator [ActPars] | number | charCon | \"new\" ident ['[' Expr ']'] | '(' Expr ')'.",
        "// SimpleFactor = Designator [ActPars] | number | charCon | \"new\" ident ['[' Expr ']'] | '(' Expr ')'."
    )
    src = src.replace(
        "private static Operand Factor() {",
        "private static Operand SimpleFactor() {"
    )

    # --- Step 4: Insert new Expr, Term, Factor, makeCond methods ---
    # Insert after the ConstDecl method (right before Designator)
    new_methods = '''
\t// Expr = Term {"||" Term}.
\tprivate static Operand Expr() {
\t\tOperand x = Term();
\t\twhile (sym == or) {
\t\t\tscan();
\t\t\tx = makeCond(x);
\t\t\tCode.tJump(x.op, x.tLabel);
\t\t\tx.fLabel.here();
\t\t\tOperand y = Term();
\t\t\ty = makeCond(y);
\t\t\tx.op = y.op;
\t\t\tx.fLabel = y.fLabel;
\t\t\tx.tLabel.merge(y.tLabel);
\t\t}
\t\treturn x;
\t}

\t// Term = Factor {"&&" Factor}.
\tprivate static Operand Term() {
\t\tOperand x = Factor();
\t\twhile (sym == and) {
\t\t\tscan();
\t\t\tx = makeCond(x);
\t\t\tCode.fJump(x.op, x.fLabel);
\t\t\tx.tLabel.here();
\t\t\tOperand y = Factor();
\t\t\ty = makeCond(y);
\t\t\tx.op = y.op;
\t\t\tx.tLabel = y.tLabel;
\t\t\tx.fLabel.merge(y.fLabel);
\t\t}
\t\treturn x;
\t}

\t// Factor = SimpleExpr [Relop SimpleExpr].
\tprivate static Operand Factor() {
\t\tOperand x = SimpleExpr();
\t\tif (sym == eql || sym == neq || sym == lss || sym == leq || sym == gtr || sym == geq) {
\t\t\tCode.load(x);
\t\t\tint op = Relop();
\t\t\tOperand y = SimpleExpr();
\t\t\tCode.load(y);
\t\t\tif (!x.type.compatibleWith(y.type)) error("type mismatch");
\t\t\tif (x.type.isRefType() && op != Code.eq && op != Code.ne) error("invalid compare");
\t\t\tx = new Operand(Operand.Cond, op, Tab.boolType);
\t\t}
\t\treturn x;
\t}

\t// Converts operand to Cond if needed (for boolean vars in conditions)
\tprivate static Operand makeCond(Operand x) {
\t\tif (x.kind == Operand.Cond) return x;
\t\tif (x.type == Tab.boolType) {
\t\t\tCode.load(x);
\t\t\tCode.put(Code.const1);
\t\t} else error("boolean expected");
\t\treturn new Operand(Operand.Cond, Code.eq, Tab.boolType);
\t}

'''
    # Insert right before the Designator comment
    insert_marker = "\t// Designator = ident"
    src = src.replace(insert_marker, new_methods + insert_marker)

    # --- Step 5: Modify if/while to use Expr + makeCond instead of Condition ---
    # The pattern in both if and while is:
    #   x = Condition();
    #   check(rpar);
    #   Code.fJump(x.op, x.fLabel);
    # Replace with:
    #   x = Expr();
    #   check(rpar);
    #   x = makeCond(x);
    #   Code.fJump(x.op, x.fLabel);

    src = src.replace(
        "x = Condition();\n\t\t\tcheck(rpar);\n\t\t\tCode.fJump(x.op, x.fLabel);",
        "x = Expr();\n\t\t\tcheck(rpar);\n\t\t\tx = makeCond(x);\n\t\t\tCode.fJump(x.op, x.fLabel);"
    )

    # --- Step 6: Modify print statement to handle boolean type ---
    src = src.replace(
        'if (x.type == Tab.intType) Code.put(Code.print);\n'
        '\t\t\telse if (x.type == Tab.charType) Code.put(Code.bprint);\n'
        '\t\t\telse error("can only print int or char variables");',
        'if (x.type == Tab.intType || x.type == Tab.boolType) Code.put(Code.print);\n'
        '\t\t\telse if (x.type == Tab.charType) Code.put(Code.bprint);\n'
        '\t\t\telse error("can only print int, char, or boolean values");'
    )

    write_file(path, src)


# ============================================================
# Main
# ============================================================
def main():
    print("Patching MicroJava compiler for boolean data type support...")
    patch_struct()
    patch_tab()
    patch_label()
    patch_code()
    patch_parser()
    print("All patches applied successfully.")


if __name__ == "__main__":
    main()
