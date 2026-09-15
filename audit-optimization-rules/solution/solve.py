#!/usr/bin/env python3
"""
Cross-Type Compiler Optimization Rule Audit — Solution

Evaluates 16 proposed algebraic rewrite rules across uint32_t, int32_t,
and uint16_t types. Detects incorrect rules AND undefined behavior.
Writes /app/verdict.json and proof programs for non-correct rules.
"""

import json
import os
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# C program that checks all 16 rules against comprehensive edge-case values.
# Uses __builtin_*_overflow to detect UB without triggering it.
# Outputs "rule_N:T", "rule_N:F:a:b", or "rule_N:U:a:b" per line.
# ---------------------------------------------------------------------------
CHECKER_SRC = r"""
#include <stdint.h>
#include <stdio.h>
#include <limits.h>

static uint32_t u32v[] = {
    0u, 1u, 2u, 3u, 4u, 5u, 7u, 8u, 15u, 16u,
    31u, 32u, 63u, 64u, 127u, 128u,
    0xFFu, 0x100u, 0x1234u,
    0x7FFFu, 0x8000u, 0xFFFFu, 0x10000u,
    0x55555555u, 0x7FFFFFFFu, 0x80000000u, 0x80000001u,
    0xAAAAAAAAu, 0xC0000000u, 0xFFFFFFFEu, 0xFFFFFFFFu
};
#define NU32 (sizeof(u32v)/sizeof(u32v[0]))

static int32_t i32v[] = {
    INT32_MIN, INT32_MIN+1, (int32_t)0xC0000000,
    -256, -128, -65, -64, -2, -1,
    0, 1, 2, 64, 65, 127, 128, 255, 256,
    (int32_t)0x3FFFFFFF, (int32_t)0x40000000,
    INT32_MAX-1, INT32_MAX
};
#define NI32 (sizeof(i32v)/sizeof(i32v[0]))

static uint16_t u16v[] = {
    0, 1, 2, 127, 128, 255, 256, 1000,
    32767, 32768, 46340, 46341, 65534, 65535
};
#define NU16 (sizeof(u16v)/sizeof(u16v[0]))

static uint32_t shv[] = {1,2,3,4,7,8,15,16,17,24,31};
#define NSH (sizeof(shv)/sizeof(shv[0]))

int main(void) {
    int i, j;

    /* Rule 1 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(((a|b)-(a&b))!=(a^b)){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_1:F:%u:%u\n",ca,cb); else printf("rule_1:T\n");
    }

    /* Rule 2 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(((a^b)|(a&b))!=(a|b)){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_2:F:%u:%u\n",ca,cb); else printf("rule_2:T\n");
    }

    /* Rule 3 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(((a+b)*(a-b))!=(a*a-b*b)){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_3:F:%u:%u\n",ca,cb); else printf("rule_3:T\n");
    }

    /* Rule 4 */ {
        int f=0; uint32_t ca=0;
        for(i=0;i<(int)NU32&&!f;i++){
            uint32_t a=u32v[i];
            if((a^0xFFFFFFFFu)!=(~a)){f=1;ca=a;}
        }
        if(f) printf("rule_4:F:%u\n",ca); else printf("rule_4:T\n");
    }

    /* Rule 5 */ {
        int ub=0,f=0; int32_t ca=0,cb=0;
        for(i=0;i<(int)NI32;i++) for(j=0;j<(int)NI32;j++){
            int32_t a=i32v[i],b=i32v[j];
            int32_t ov=a|b,av=a&b,sr;
            if(__builtin_sub_overflow(ov,av,&sr)){if(!ub){ub=1;ca=a;cb=b;}}
            else if(!f&&sr!=(a^b)){f=1;ca=a;cb=b;}
        }
        if(ub) printf("rule_5:U:%d:%d\n",(int)ca,(int)cb);
        else if(f) printf("rule_5:F:%d:%d\n",(int)ca,(int)cb);
        else printf("rule_5:T\n");
    }

    /* Rule 6 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(((a&~b)|(~a&b))!=(~(a^b))){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_6:F:%u:%u\n",ca,cb); else printf("rule_6:T\n");
    }

    /* Rule 7 */ {
        int f=0; uint32_t ca=0,cn=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NSH&&!f;j++){
            uint32_t a=u32v[i],n=shv[j];
            if(((a<<n)>>n)!=a){f=1;ca=a;cn=n;}
        }
        if(f) printf("rule_7:F:%u:%u\n",ca,cn); else printf("rule_7:T\n");
    }

    /* Rule 8 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(b==0) continue;
            if(((a*b)/b)!=a){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_8:F:%u:%u\n",ca,cb); else printf("rule_8:T\n");
    }

    /* Rule 9 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(((a>>1)+(b>>1)+((a|b)&1u))!=((a+b)>>1)){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_9:F:%u:%u\n",ca,cb); else printf("rule_9:T\n");
    }

    /* Rule 10 */ {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i],b=u32v[j];
            if(((a^b)|((a&b)<<1))!=(a+b)){f=1;ca=a;cb=b;}
        }
        if(f) printf("rule_10:F:%u:%u\n",ca,cb); else printf("rule_10:T\n");
    }

    /* Rule 11 */ {
        int f=0; uint32_t ca=0,cn=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NSH&&!f;j++){
            uint32_t a=u32v[i],n=shv[j];
            if(((a>>n)<<n)!=a){f=1;ca=a;cn=n;}
        }
        if(f) printf("rule_11:F:%u:%u\n",ca,cn); else printf("rule_11:T\n");
    }

    /* Rule 12 */ {
        int ub=0,f=0; int32_t ca=0;
        for(i=0;i<(int)NI32;i++){
            int32_t a=i32v[i],res;
            if(__builtin_add_overflow(a,(int32_t)1,&res)){if(!ub){ub=1;ca=a;}}
            else if(!f&&!((a+1)>a)){f=1;ca=a;}
        }
        if(ub) printf("rule_12:U:%d\n",(int)ca);
        else if(f) printf("rule_12:F:%d\n",(int)ca);
        else printf("rule_12:T\n");
    }

    /* Rule 13 */ {
        int ub=0,f=0; int32_t ca=0;
        for(i=0;i<(int)NI32;i++){
            int32_t a=i32v[i],neg;
            if(__builtin_sub_overflow((int32_t)0,a,&neg)){if(!ub){ub=1;ca=a;}continue;}
            int32_t neg2;
            if(__builtin_sub_overflow((int32_t)0,neg,&neg2)){if(!ub){ub=1;ca=a;}continue;}
            if(!f&&neg2!=a){f=1;ca=a;}
        }
        if(ub) printf("rule_13:U:%d\n",(int)ca);
        else if(f) printf("rule_13:F:%d\n",(int)ca);
        else printf("rule_13:T\n");
    }

    /* Rule 14 */ {
        int ub=0,f=0; uint16_t ca=0,cb=0;
        for(i=0;i<(int)NU16;i++) for(j=0;j<(int)NU16;j++){
            uint16_t a=u16v[i],b=u16v[j]; int prod;
            if(__builtin_mul_overflow((int)a,(int)b,&prod)){
                if(!ub){ub=1;ca=a;cb=b;}
            } else if(!f&&(uint16_t)((uint32_t)a*(uint32_t)b)!=(uint16_t)(a*b)){
                f=1;ca=a;cb=b;
            }
        }
        if(ub) printf("rule_14:U:%u:%u\n",(unsigned)ca,(unsigned)cb);
        else if(f) printf("rule_14:F:%u:%u\n",(unsigned)ca,(unsigned)cb);
        else printf("rule_14:T\n");
    }

    /* Rule 15 */ {
        int ub=0,f=0; int32_t ca=0,cb=0;
        for(i=0;i<(int)NI32;i++) for(j=0;j<(int)NI32;j++){
            int32_t a=i32v[i],b=i32v[j]; if(b<=0) continue;
            int32_t prod;
            if(__builtin_mul_overflow(a,b,&prod)){if(!ub){ub=1;ca=a;cb=b;}}
            else if(!f&&(a*b/b)!=a){f=1;ca=a;cb=b;}
        }
        if(ub) printf("rule_15:U:%d:%d\n",(int)ca,(int)cb);
        else if(f) printf("rule_15:F:%d:%d\n",(int)ca,(int)cb);
        else printf("rule_15:T\n");
    }

    /* Rule 16 */ {
        int ub=0,f=0; int32_t ca=0;
        for(i=0;i<(int)NI32;i++){
            int32_t a=i32v[i]; if(a==0) continue;
            if(a==INT32_MIN){if(!ub){ub=1;ca=a;}continue;}
            if(!f&&(a/-1)!=(-a)){f=1;ca=a;}
        }
        if(ub) printf("rule_16:U:%d\n",(int)ca);
        else if(f) printf("rule_16:F:%d\n",(int)ca);
        else printf("rule_16:T\n");
    }

    return 0;
}
"""

# ---------------------------------------------------------------------------
# Rule expression definitions for generating proof programs
# ---------------------------------------------------------------------------
RULE_DEFS = {
    1:  {"type": "u32", "vars": "ab", "lhs": "((a|b)-(a&b))", "rhs": "(a^b)"},
    2:  {"type": "u32", "vars": "ab", "lhs": "((a^b)|(a&b))", "rhs": "(a|b)"},
    3:  {"type": "u32", "vars": "ab", "lhs": "((a+b)*(a-b))", "rhs": "(a*a-b*b)"},
    4:  {"type": "u32", "vars": "a",  "lhs": "(a^0xFFFFFFFFu)", "rhs": "(~a)"},
    5:  {"type": "i32", "vars": "ab", "lhs": "((a|b)-(a&b))", "rhs": "(a^b)"},
    6:  {"type": "u32", "vars": "ab", "lhs": "((a&~b)|(~a&b))", "rhs": "(~(a^b))"},
    7:  {"type": "u32", "vars": "an", "lhs": "((a<<n)>>n)", "rhs": "a"},
    8:  {"type": "u32", "vars": "ab", "lhs": "((a*b)/b)", "rhs": "a"},
    9:  {"type": "u32", "vars": "ab", "lhs": "((a>>1)+(b>>1)+((a|b)&1u))", "rhs": "((a+b)>>1)"},
    10: {"type": "u32", "vars": "ab", "lhs": "((a^b)|((a&b)<<1))", "rhs": "(a+b)"},
    11: {"type": "u32", "vars": "an", "lhs": "((a>>n)<<n)", "rhs": "a"},
    12: {"type": "i32_ub_add", "vars": "a"},
    13: {"type": "i32_ub_neg", "vars": "a"},
    14: {"type": "u16_ub_mul", "vars": "ab"},
    15: {"type": "i32_ub_mul", "vars": "ab"},
    16: {"type": "i32_ub_div", "vars": "a"},
}


def main():
    # Step 1: Write and compile the checker
    checker_src = "/tmp/rule_checker.c"
    checker_bin = "/tmp/rule_checker"
    with open(checker_src, "w") as f:
        f.write(CHECKER_SRC)
    comp = subprocess.run(
        ["gcc", "-O0", checker_src, "-o", checker_bin],
        capture_output=True, text=True, timeout=30,
    )
    if comp.returncode != 0:
        print(f"ERROR: Checker compile failed: {comp.stderr}")
        return
    print("Compiled rule checker.")

    # Step 2: Run the checker
    result = subprocess.run(
        [checker_bin], capture_output=True, text=True, timeout=120,
    )
    print(f"Checker output:\n{result.stdout}")

    # Step 3: Parse results
    verdict = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.split(":")
        rule = parts[0]
        rule_num = int(rule.split("_")[1])
        code = parts[1]
        defn = RULE_DEFS[rule_num]

        if code == "T":
            verdict[rule] = {"verdict": "correct", "witness": None}
        elif code == "F":
            a = int(parts[2])
            if len(parts) > 3:
                second = int(parts[3])
            else:
                second = None
            if defn["vars"] == "an":
                wit = {"a": a, "n": second}
            elif defn["vars"] == "a":
                wit = {"a": a}
            else:
                wit = {"a": a, "b": second}
            verdict[rule] = {"verdict": "incorrect", "witness": wit}
        elif code == "U":
            a_raw = parts[2]
            a = int(a_raw)
            if len(parts) > 3:
                second = int(parts[3])
            else:
                second = None
            if defn["vars"] == "an":
                wit = {"a": a, "n": second}
            elif defn["vars"] == "a":
                wit = {"a": a}
            else:
                wit = {"a": a, "b": second}
            verdict[rule] = {"verdict": "undefined_behavior", "witness": wit}

    # Step 4: Write verdict.json
    with open("/app/verdict.json", "w") as f:
        json.dump(verdict, f, indent=2)
    print("Wrote /app/verdict.json")

    # Step 5: Write proof programs for non-correct rules
    os.makedirs("/app/proof", exist_ok=True)
    for rule, v in sorted(verdict.items()):
        if v["verdict"] != "correct":
            rule_num = int(rule.split("_")[1])
            write_proof(rule_num, v["verdict"], v["witness"])

    print("\nFinal verdict:")
    print(json.dumps(verdict, indent=2))


def write_proof(rule_num, verdict_type, witness):
    """Generate a proof program for a non-correct rule."""
    defn = RULE_DEFS[rule_num]
    a_val = witness["a"]

    if verdict_type == "incorrect":
        write_incorrect_proof(rule_num, defn, witness)
    elif verdict_type == "undefined_behavior":
        write_ub_proof(rule_num, defn, witness)


def write_incorrect_proof(rule_num, defn, witness):
    """Proof for incorrect rules: show LHS != RHS."""
    a_val = witness["a"]
    lines = [
        "#include <stdint.h>",
        "#include <stdio.h>",
        "",
        "int main(void) {",
    ]

    c_type = "uint32_t" if defn["type"] == "u32" else "int32_t"

    if defn["vars"] == "an":
        n_val = witness["n"]
        lines.append(f"    {c_type} a = {a_val}u;")
        lines.append(f"    {c_type} n = {n_val}u;")
        var_fmt = "a=%u n=%u"
        var_args = "a, n"
    elif defn["vars"] == "a":
        lines.append(f"    {c_type} a = {a_val}u;")
        var_fmt = "a=%u"
        var_args = "a"
    else:
        b_val = witness["b"]
        lines.append(f"    {c_type} a = {a_val}u;")
        lines.append(f"    {c_type} b = {b_val}u;")
        var_fmt = "a=%u b=%u"
        var_args = "a, b"

    lines.extend([
        f"    {c_type} lhs = {defn['lhs']};",
        f"    {c_type} rhs = {defn['rhs']};",
        "    if (lhs != rhs) {",
        f'        printf("FAIL: rule_{rule_num} counterexample {var_fmt}'
        f' lhs=%u rhs=%u\\n", {var_args}, lhs, rhs);',
        "        return 0;",
        "    }",
        '    printf("PASS\\n");',
        "    return 1;",
        "}",
    ])

    source = "\n".join(lines) + "\n"
    write_and_verify_proof(rule_num, source)


def write_ub_proof(rule_num, defn, witness):
    """Proof for UB rules: detect overflow condition."""
    a_val = witness["a"]
    lines = [
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <limits.h>",
        "",
        "int main(void) {",
    ]

    ub_type = defn["type"]

    if ub_type == "i32_ub_add":
        lines.extend([
            f"    int32_t a = {a_val};",
            "    int32_t res;",
            "    if (__builtin_add_overflow(a, (int32_t)1, &res)) {",
            f'        printf("FAIL: rule_{rule_num} a=%d triggers signed overflow in (a+1)\\n", a);',
            "        return 0;",
            "    }",
        ])
    elif ub_type == "i32_ub_neg":
        lines.extend([
            f"    int32_t a = {a_val};",
            "    int32_t neg;",
            "    if (__builtin_sub_overflow((int32_t)0, a, &neg)) {",
            f'        printf("FAIL: rule_{rule_num} a=%d triggers signed overflow in -a\\n", a);',
            "        return 0;",
            "    }",
            "    int32_t neg2;",
            "    if (__builtin_sub_overflow((int32_t)0, neg, &neg2)) {",
            f'        printf("FAIL: rule_{rule_num} a=%d triggers signed overflow in -(-a)\\n", a);',
            "        return 0;",
            "    }",
        ])
    elif ub_type == "u16_ub_mul":
        b_val = witness["b"]
        lines.extend([
            f"    uint16_t a = {a_val};",
            f"    uint16_t b = {b_val};",
            "    int prod;",
            "    /* uint16_t promotes to int; multiplication can overflow signed int */",
            "    if (__builtin_mul_overflow((int)a, (int)b, &prod)) {",
            f'        printf("FAIL: rule_{rule_num} a=%u b=%u triggers signed int overflow '
            f'via uint16_t promotion: (int)%u * (int)%u overflows\\n",'
            f' (unsigned)a, (unsigned)b, (unsigned)a, (unsigned)b);',
            "        return 0;",
            "    }",
        ])
    elif ub_type == "i32_ub_mul":
        b_val = witness["b"]
        lines.extend([
            f"    int32_t a = {a_val};",
            f"    int32_t b = {b_val};",
            "    int32_t prod;",
            "    if (__builtin_mul_overflow(a, b, &prod)) {",
            f'        printf("FAIL: rule_{rule_num} a=%d b=%d triggers signed overflow in a*b\\n", a, b);',
            "        return 0;",
            "    }",
        ])
    elif ub_type == "i32_ub_div":
        lines.extend([
            f"    int32_t a = {a_val};",
            "    if (a == INT32_MIN) {",
            f'        printf("FAIL: rule_{rule_num} a=%d (INT_MIN): a/-1 and -a both overflow\\n", a);',
            "        return 0;",
            "    }",
        ])

    lines.extend([
        '    printf("PASS\\n");',
        "    return 1;",
        "}",
    ])

    source = "\n".join(lines) + "\n"
    write_and_verify_proof(rule_num, source)


def write_and_verify_proof(rule_num, source):
    """Write proof program and verify it works."""
    proof_path = f"/app/proof/rule_{rule_num}.c"
    with open(proof_path, "w") as f:
        f.write(source)

    binary = f"/tmp/proof_rule_{rule_num}"
    comp = subprocess.run(
        ["gcc", "-O0", proof_path, "-o", binary],
        capture_output=True, text=True, timeout=30,
    )
    if comp.returncode != 0:
        print(f"WARNING: Proof for rule_{rule_num} failed to compile: {comp.stderr}")
        return
    run = subprocess.run(
        [binary], capture_output=True, text=True, timeout=15,
    )
    print(f"Proof rule_{rule_num}: {run.stdout.strip()} (exit {run.returncode})")
    if os.path.exists(binary):
        os.unlink(binary)


if __name__ == "__main__":
    main()
