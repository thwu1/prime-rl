
import json
import os
import subprocess
import tempfile

import pytest

RULES = [f"rule_{i}" for i in range(1, 17)]

# ---------------------------------------------------------------------------
# C program: checks all 16 rules against comprehensive edge-case values.
# Outputs "rule_N:T" (correct), "rule_N:F:a:b" (incorrect), or
# "rule_N:U:a:b" (undefined behavior) per line.
#
# UB detection uses GCC __builtin_*_overflow intrinsics to check for
# potential overflow WITHOUT actually triggering undefined behavior.
# ---------------------------------------------------------------------------
VERIFY_SOURCE = r"""
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
    INT32_MIN,
    INT32_MIN + 1,
    (int32_t)0xC0000000,
    -256, -128, -65, -64, -2, -1,
    0, 1, 2, 64, 65, 127, 128, 255, 256,
    (int32_t)0x3FFFFFFF,
    (int32_t)0x40000000,
    INT32_MAX - 1,
    INT32_MAX
};
#define NI32 (sizeof(i32v)/sizeof(i32v[0]))

static uint16_t u16v[] = {
    0, 1, 2, 127, 128, 255, 256, 1000,
    32767, 32768, 46340, 46341, 65534, 65535
};
#define NU16 (sizeof(u16v)/sizeof(u16v[0]))

static uint32_t shv[] = {1, 2, 3, 4, 7, 8, 15, 16, 17, 24, 31};
#define NSH (sizeof(shv)/sizeof(shv[0]))

int main(void) {
    int i, j;

    /* Rule 1: uint32_t (a|b)-(a&b) == a^b */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(((a|b)-(a&b)) != (a^b)){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_1:F:%u:%u\n",ca,cb); else printf("rule_1:T\n");
    }

    /* Rule 2: uint32_t (a^b)|(a&b) == a|b */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(((a^b)|(a&b)) != (a|b)){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_2:F:%u:%u\n",ca,cb); else printf("rule_2:T\n");
    }

    /* Rule 3: uint32_t (a+b)*(a-b) == a*a-b*b */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(((a+b)*(a-b)) != (a*a-b*b)){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_3:F:%u:%u\n",ca,cb); else printf("rule_3:T\n");
    }

    /* Rule 4: uint32_t a^0xFFFFFFFF == ~a */
    {
        int f=0; uint32_t ca=0;
        for(i=0;i<(int)NU32&&!f;i++){
            uint32_t a=u32v[i];
            if((a^0xFFFFFFFFu) != (~a)){ f=1; ca=a; }
        }
        if(f) printf("rule_4:F:%u\n",ca); else printf("rule_4:T\n");
    }

    /* Rule 5: int32_t (a|b)-(a&b) == a^b — check overflow via builtin */
    {
        int ub=0, f=0; int32_t ca=0,cb=0;
        for(i=0;i<(int)NI32;i++) for(j=0;j<(int)NI32;j++){
            int32_t a=i32v[i], b=i32v[j];
            int32_t or_val=a|b, and_val=a&b, sub_res;
            if(__builtin_sub_overflow(or_val, and_val, &sub_res)){
                if(!ub){ ub=1; ca=a; cb=b; }
            } else if(!f && sub_res != (a^b)){
                f=1; ca=a; cb=b;
            }
        }
        if(ub) printf("rule_5:U:%d:%d\n",(int)ca,(int)cb);
        else if(f) printf("rule_5:F:%d:%d\n",(int)ca,(int)cb);
        else printf("rule_5:T\n");
    }

    /* Rule 6: uint32_t (a&~b)|(~a&b) == ~(a^b) */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(((a&~b)|(~a&b)) != (~(a^b))){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_6:F:%u:%u\n",ca,cb); else printf("rule_6:T\n");
    }

    /* Rule 7: uint32_t (a<<n)>>n == a */
    {
        int f=0; uint32_t ca=0,cn=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NSH&&!f;j++){
            uint32_t a=u32v[i], n=shv[j];
            if(((a<<n)>>n) != a){ f=1; ca=a; cn=n; }
        }
        if(f) printf("rule_7:F:%u:%u\n",ca,cn); else printf("rule_7:T\n");
    }

    /* Rule 8: uint32_t (a*b)/b == a, b!=0 */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(b==0) continue;
            if(((a*b)/b) != a){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_8:F:%u:%u\n",ca,cb); else printf("rule_8:T\n");
    }

    /* Rule 9: uint32_t (a>>1)+(b>>1)+((a|b)&1) == (a+b)>>1 */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(((a>>1)+(b>>1)+((a|b)&1u)) != ((a+b)>>1)){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_9:F:%u:%u\n",ca,cb); else printf("rule_9:T\n");
    }

    /* Rule 10: uint32_t (a^b)|((a&b)<<1) == a+b */
    {
        int f=0; uint32_t ca=0,cb=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NU32&&!f;j++){
            uint32_t a=u32v[i], b=u32v[j];
            if(((a^b)|((a&b)<<1)) != (a+b)){ f=1; ca=a; cb=b; }
        }
        if(f) printf("rule_10:F:%u:%u\n",ca,cb); else printf("rule_10:T\n");
    }

    /* Rule 11: uint32_t (a>>n)<<n == a */
    {
        int f=0; uint32_t ca=0,cn=0;
        for(i=0;i<(int)NU32&&!f;i++) for(j=0;j<(int)NSH&&!f;j++){
            uint32_t a=u32v[i], n=shv[j];
            if(((a>>n)<<n) != a){ f=1; ca=a; cn=n; }
        }
        if(f) printf("rule_11:F:%u:%u\n",ca,cn); else printf("rule_11:T\n");
    }

    /* Rule 12: int32_t (a+1)>a == 1 */
    {
        int ub=0, f=0; int32_t ca=0;
        for(i=0;i<(int)NI32;i++){
            int32_t a=i32v[i], res;
            if(__builtin_add_overflow(a, (int32_t)1, &res)){
                if(!ub){ ub=1; ca=a; }
            } else if(!f && !((a+1)>a)){
                f=1; ca=a;
            }
        }
        if(ub) printf("rule_12:U:%d\n",(int)ca);
        else if(f) printf("rule_12:F:%d\n",(int)ca);
        else printf("rule_12:T\n");
    }

    /* Rule 13: int32_t -(-a) == a */
    {
        int ub=0, f=0; int32_t ca=0;
        for(i=0;i<(int)NI32;i++){
            int32_t a=i32v[i], neg;
            if(__builtin_sub_overflow((int32_t)0, a, &neg)){
                if(!ub){ ub=1; ca=a; }
                continue;
            }
            int32_t neg2;
            if(__builtin_sub_overflow((int32_t)0, neg, &neg2)){
                if(!ub){ ub=1; ca=a; }
                continue;
            }
            if(!f && neg2 != a){
                f=1; ca=a;
            }
        }
        if(ub) printf("rule_13:U:%d\n",(int)ca);
        else if(f) printf("rule_13:F:%d\n",(int)ca);
        else printf("rule_13:T\n");
    }

    /* Rule 14: uint16_t (uint16_t)((uint32_t)a*(uint32_t)b) == (uint16_t)(a*b) */
    {
        int ub=0, f=0; uint16_t ca=0,cb=0;
        for(i=0;i<(int)NU16;i++) for(j=0;j<(int)NU16;j++){
            uint16_t a=u16v[i], b=u16v[j];
            int prod;
            if(__builtin_mul_overflow((int)a, (int)b, &prod)){
                if(!ub){ ub=1; ca=a; cb=b; }
            } else if(!f){
                if((uint16_t)((uint32_t)a*(uint32_t)b) != (uint16_t)(a*b)){
                    f=1; ca=a; cb=b;
                }
            }
        }
        if(ub) printf("rule_14:U:%u:%u\n",(unsigned)ca,(unsigned)cb);
        else if(f) printf("rule_14:F:%u:%u\n",(unsigned)ca,(unsigned)cb);
        else printf("rule_14:T\n");
    }

    /* Rule 15: int32_t a*b/b == a, b>0 */
    {
        int ub=0, f=0; int32_t ca=0,cb=0;
        for(i=0;i<(int)NI32;i++) for(j=0;j<(int)NI32;j++){
            int32_t a=i32v[i], b=i32v[j];
            if(b<=0) continue;
            int32_t prod;
            if(__builtin_mul_overflow(a, b, &prod)){
                if(!ub){ ub=1; ca=a; cb=b; }
            } else if(!f && (a*b/b) != a){
                f=1; ca=a; cb=b;
            }
        }
        if(ub) printf("rule_15:U:%d:%d\n",(int)ca,(int)cb);
        else if(f) printf("rule_15:F:%d:%d\n",(int)ca,(int)cb);
        else printf("rule_15:T\n");
    }

    /* Rule 16: int32_t a/-1 == -a, a!=0 */
    {
        int ub=0, f=0; int32_t ca=0;
        for(i=0;i<(int)NI32;i++){
            int32_t a=i32v[i];
            if(a==0) continue;
            /* a / -1 overflows iff a == INT_MIN; -a overflows iff a == INT_MIN */
            if(a == INT32_MIN){
                if(!ub){ ub=1; ca=a; }
                continue;
            }
            if(!f && (a / -1) != (-a)){
                f=1; ca=a;
            }
        }
        if(ub) printf("rule_16:U:%d\n",(int)ca);
        else if(f) printf("rule_16:F:%d\n",(int)ca);
        else printf("rule_16:T\n");
    }

    return 0;
}
"""

# ---------------------------------------------------------------------------
# C program: validates a single witness for a given rule.
# Usage: ./checker <rule_num> <a> <b_or_n>
# Exit 0 = rule holds (witness invalid), Exit 1 = rule violated or UB found.
# For rules 1-11 (non-UB): checks LHS != RHS.
# For rules 12-16 (UB-possible): checks if UB would occur.
# For rule 5 (signed but correct): checks for overflow, then LHS != RHS.
# ---------------------------------------------------------------------------
CHECKER_SOURCE = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>

int check_rule(int rule, uint32_t a_raw, uint32_t b_raw) {
    switch(rule) {
        case 1: {
            uint32_t a=a_raw, b=b_raw;
            return ((a|b)-(a&b)) == (a^b);
        }
        case 2: {
            uint32_t a=a_raw, b=b_raw;
            return ((a^b)|(a&b)) == (a|b);
        }
        case 3: {
            uint32_t a=a_raw, b=b_raw;
            return ((a+b)*(a-b)) == (a*a-b*b);
        }
        case 4: {
            uint32_t a=a_raw;
            return (a^0xFFFFFFFFu) == (~a);
        }
        case 5: {
            int32_t a=(int32_t)a_raw, b=(int32_t)b_raw;
            int32_t or_v=a|b, and_v=a&b, sub_r;
            if(__builtin_sub_overflow(or_v, and_v, &sub_r)) return 0;
            return sub_r == (a^b);
        }
        case 6: {
            uint32_t a=a_raw, b=b_raw;
            return ((a&~b)|(~a&b)) == (~(a^b));
        }
        case 7: {
            uint32_t a=a_raw, n=b_raw;
            return (n>0&&n<32) ? (((a<<n)>>n)==a) : 1;
        }
        case 8: {
            uint32_t a=a_raw, b=b_raw;
            return (b==0) ? 1 : (((a*b)/b)==a);
        }
        case 9: {
            uint32_t a=a_raw, b=b_raw;
            return ((a>>1)+(b>>1)+((a|b)&1u))==((a+b)>>1);
        }
        case 10: {
            uint32_t a=a_raw, b=b_raw;
            return ((a^b)|((a&b)<<1)) == (a+b);
        }
        case 11: {
            uint32_t a=a_raw, n=b_raw;
            return (n>0&&n<32) ? (((a>>n)<<n)==a) : 1;
        }
        case 12: {
            int32_t a=(int32_t)a_raw;
            int32_t res;
            if(__builtin_add_overflow(a, (int32_t)1, &res)) return 0;
            return (a+1) > a;
        }
        case 13: {
            int32_t a=(int32_t)a_raw;
            int32_t neg;
            if(__builtin_sub_overflow((int32_t)0, a, &neg)) return 0;
            int32_t neg2;
            if(__builtin_sub_overflow((int32_t)0, neg, &neg2)) return 0;
            return neg2 == a;
        }
        case 14: {
            uint16_t a=(uint16_t)(a_raw & 0xFFFF);
            uint16_t b=(uint16_t)(b_raw & 0xFFFF);
            int res;
            if(__builtin_mul_overflow((int)a, (int)b, &res)) return 0;
            return (uint16_t)((uint32_t)a*(uint32_t)b) == (uint16_t)(a*b);
        }
        case 15: {
            int32_t a=(int32_t)a_raw, b=(int32_t)b_raw;
            if(b<=0) return 1;
            int32_t prod;
            if(__builtin_mul_overflow(a, b, &prod)) return 0;
            return (a*b/b)==a;
        }
        case 16: {
            int32_t a=(int32_t)a_raw;
            if(a==0) return 1;
            if(a==INT32_MIN) return 0;
            return (a / -1) == (-a);
        }
        default: return -1;
    }
}

int main(int argc, char *argv[]) {
    if(argc!=4){fprintf(stderr,"Usage: %s rule a b\n",argv[0]);return 2;}
    int rule = atoi(argv[1]);
    uint32_t a = (uint32_t)strtoul(argv[2],NULL,10);
    uint32_t b = (uint32_t)strtoul(argv[3],NULL,10);
    int holds = check_rule(rule,a,b);
    printf("%d\n", holds);
    return holds ? 0 : 1;
}
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def verdict():
    """Load agent's verdict.json."""
    path = "/app/verdict.json"
    assert os.path.exists(path), "verdict.json not found at /app/verdict.json"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def ground_truth():
    """Compile and run verification program to determine ground truth."""
    with tempfile.NamedTemporaryFile(
        suffix=".c", mode="w", delete=False
    ) as f:
        f.write(VERIFY_SOURCE)
        src = f.name
    binary = src + ".bin"
    try:
        comp = subprocess.run(
            ["gcc", "-O0", src, "-o", binary],
            capture_output=True, text=True, timeout=30,
        )
        assert comp.returncode == 0, (
            f"Verification program failed to compile: {comp.stderr}"
        )
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=120,
        )
        assert run.returncode == 0, (
            f"Verification program failed: {run.stderr}"
        )
        truth = {}
        for line in run.stdout.strip().split("\n"):
            parts = line.split(":")
            rule = parts[0]
            code = parts[1]
            if code == "T":
                truth[rule] = {"verdict": "correct"}
            elif code == "F":
                truth[rule] = {"verdict": "incorrect"}
            elif code == "U":
                truth[rule] = {"verdict": "undefined_behavior"}
        return truth
    finally:
        for p in [src, binary]:
            if os.path.exists(p):
                os.unlink(p)


@pytest.fixture(scope="module")
def checker_binary():
    """Compile the witness checker binary."""
    with tempfile.NamedTemporaryFile(
        suffix=".c", mode="w", delete=False
    ) as f:
        f.write(CHECKER_SOURCE)
        src = f.name
    binary = src + ".bin"
    comp = subprocess.run(
        ["gcc", "-O0", src, "-o", binary],
        capture_output=True, text=True, timeout=30,
    )
    assert comp.returncode == 0, (
        f"Checker failed to compile: {comp.stderr}"
    )
    yield binary
    for p in [src, binary]:
        if os.path.exists(p):
            os.unlink(p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_verdict_exists(verdict):
    """verdict.json must exist and be valid JSON dict."""
    assert isinstance(verdict, dict)


def test_all_rules_present(verdict):
    """All 16 rules must have entries."""
    for rule in RULES:
        assert rule in verdict, f"Missing entry for {rule}"


def test_required_fields(verdict):
    """Each entry must have verdict and witness fields."""
    for rule in RULES:
        entry = verdict[rule]
        assert "verdict" in entry, f"{rule} missing 'verdict'"
        assert "witness" in entry, f"{rule} missing 'witness'"


def test_valid_verdict_values(verdict):
    """Each verdict must be one of the three allowed values."""
    allowed = {"correct", "incorrect", "undefined_behavior"}
    for rule in RULES:
        v = verdict[rule]["verdict"]
        assert v in allowed, (
            f"{rule}: verdict '{v}' not in {allowed}"
        )


@pytest.mark.parametrize("rule", RULES)
def test_verdict(verdict, ground_truth, rule):
    """Agent's verdict must match dynamically computed ground truth."""
    expected = ground_truth[rule]["verdict"]
    actual = verdict[rule]["verdict"]
    assert actual == expected, (
        f"{rule}: verdict should be '{expected}', got '{actual}'"
    )


@pytest.mark.parametrize("rule", RULES)
def test_witness_consistency(verdict, ground_truth, rule):
    """Correct rules: witness null. Non-correct rules: witness present."""
    expected_verdict = ground_truth[rule]["verdict"]
    wit = verdict[rule]["witness"]
    if expected_verdict == "correct":
        assert wit is None, (
            f"{rule} is correct but witness is not null: {wit}"
        )
    else:
        assert wit is not None, (
            f"{rule} is {expected_verdict} but witness is null"
        )


@pytest.mark.parametrize("rule", RULES)
def test_witness_valid(verdict, ground_truth, checker_binary, rule):
    """For non-correct rules, witness values must demonstrate the defect."""
    if ground_truth[rule]["verdict"] == "correct":
        return
    wit = verdict[rule]["witness"]
    if wit is None:
        pytest.skip("No witness provided")
    rule_num = int(rule.split("_")[1])
    a = int(wit["a"])
    if "n" in wit:
        b = int(wit["n"])
    elif "b" in wit:
        b = int(wit["b"])
    else:
        b = 0
    # Handle negative values for signed rules: pass as unsigned bit pattern
    a_arg = str(a & 0xFFFFFFFF) if a < 0 else str(a)
    b_arg = str(b & 0xFFFFFFFF) if b < 0 else str(b)
    result = subprocess.run(
        [checker_binary, str(rule_num), a_arg, b_arg],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 1, (
        f"{rule}: witness (a={a}, b/n={b}) does not demonstrate the defect. "
        f"Checker output: {result.stdout.strip()}"
    )


@pytest.mark.parametrize("rule", RULES)
def test_proof_program_exists(verdict, ground_truth, rule):
    """For non-correct rules, a proof program must exist."""
    if ground_truth[rule]["verdict"] == "correct":
        return
    rule_num = int(rule.split("_")[1])
    proof_path = f"/app/proof/rule_{rule_num}.c"
    assert os.path.exists(proof_path), (
        f"Missing proof program: {proof_path}"
    )


@pytest.mark.parametrize("rule", RULES)
def test_proof_program_compiles(verdict, ground_truth, rule):
    """For non-correct rules, proof program must compile."""
    if ground_truth[rule]["verdict"] == "correct":
        return
    rule_num = int(rule.split("_")[1])
    proof_path = f"/app/proof/rule_{rule_num}.c"
    if not os.path.exists(proof_path):
        pytest.skip("Proof program missing")
    binary = f"/tmp/proof_test_{rule_num}"
    comp = subprocess.run(
        ["gcc", "-O0", proof_path, "-o", binary],
        capture_output=True, text=True, timeout=30,
    )
    assert comp.returncode == 0, (
        f"Proof program for {rule} failed to compile: {comp.stderr}"
    )
    if os.path.exists(binary):
        os.unlink(binary)


@pytest.mark.parametrize("rule", RULES)
def test_proof_program_demonstrates_defect(verdict, ground_truth, rule):
    """For non-correct rules, proof program must run, output FAIL, exit 0."""
    if ground_truth[rule]["verdict"] == "correct":
        return
    rule_num = int(rule.split("_")[1])
    proof_path = f"/app/proof/rule_{rule_num}.c"
    if not os.path.exists(proof_path):
        pytest.skip("Proof program missing")
    binary = f"/tmp/proof_run_{rule_num}"
    comp = subprocess.run(
        ["gcc", "-O0", proof_path, "-o", binary],
        capture_output=True, text=True, timeout=30,
    )
    if comp.returncode != 0:
        pytest.skip("Proof program does not compile")
    try:
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=15,
        )
        assert run.returncode == 0, (
            f"Proof program for {rule} exited with code {run.returncode}. "
            f"stdout: {run.stdout.strip()}"
        )
        assert "FAIL" in run.stdout, (
            f"Proof program for {rule} did not output FAIL. "
            f"stdout: {run.stdout.strip()}"
        )
    finally:
        if os.path.exists(binary):
            os.unlink(binary)
