#!/usr/bin/env python3
"""Generate three firmware binaries for OOO VM security audit challenge.
This script runs during Docker build only and is NOT included in the final image."""
import struct, sys, os, json

# Opcodes matching ooovm.c FC_* defines
NOP=0x00;LI8=0x01;LI16=0x02;DRP=0x03;CPY=0x04;SWP=0x05
INC=0x06;DEC=0x07;AD2=0x08;SB2=0x09;ML2=0x0A;DV2=0x0B
RM2=0x0C;AN2=0x0D;OR2=0x0E;XR2=0x0F;NT1=0x10;SL2=0x11
SR2=0x12;TEQ=0x13;TLT=0x14;TGT=0x15;JMA=0x16;JZA=0x17
JNA=0x18;CLA=0x19;RBK=0x1A;LDM=0x1B;STM=0x1C;RDI=0x1D
WRO=0x1E;HLT=0x1F;OVR=0x20

class Asm:
    def __init__(self):
        self.buf = bytearray()
        self.labels = {}
        self.refs = []
    def pos(self): return len(self.buf)
    def emit(self, *bs):
        for b in bs: self.buf.append(b & 0xff)
    def e16(self, v): self.emit(v & 0xff, (v >> 8) & 0xff)
    def label(self, n): self.labels[n] = self.pos()
    def ref(self, n):
        if n in self.labels: self.e16(self.labels[n])
        else: self.refs.append((self.pos(), n)); self.e16(0)
    def resolve(self):
        for off, n in self.refs:
            a = self.labels[n]
            self.buf[off] = a & 0xff; self.buf[off+1] = (a >> 8) & 0xff
    def li8(self, v): self.emit(LI8, v & 0xff)
    def li16(self, v): self.emit(LI16); self.e16(v)
    def drp(self): self.emit(DRP)
    def cpy(self): self.emit(CPY)
    def swp(self): self.emit(SWP)
    def inc(self): self.emit(INC)
    def dec(self): self.emit(DEC)
    def ad2(self): self.emit(AD2)
    def sb2(self): self.emit(SB2)
    def ml2(self): self.emit(ML2)
    def an2(self): self.emit(AN2)
    def or2(self): self.emit(OR2)
    def xr2(self): self.emit(XR2)
    def sl2(self): self.emit(SL2)
    def sr2(self): self.emit(SR2)
    def teq(self): self.emit(TEQ)
    def tlt(self): self.emit(TLT)
    def tgt(self): self.emit(TGT)
    def jma(self, l): self.emit(JMA); self.ref(l)
    def jza(self, l): self.emit(JZA); self.ref(l)
    def jna(self, l): self.emit(JNA); self.ref(l)
    def cla(self, l): self.emit(CLA); self.ref(l)
    def rbk(self): self.emit(RBK)
    def ldm(self): self.emit(LDM)
    def stm(self): self.emit(STM)
    def rdi(self): self.emit(RDI)
    def wro(self): self.emit(WRO)
    def hlt(self): self.emit(HLT)
    def ovr(self): self.emit(OVR)
    def pstr(self, s):
        for c in s: self.li8(ord(c)); self.wro()
    def build(self, entry='main'):
        self.resolve()
        ep = self.labels.get(entry, 0)
        return b'OOOV' + struct.pack('<HH', 1, ep) + bytes(self.buf)


# =====================================================================
# AUTH ALPHA — Hidden backdoor vulnerability (CWE-912)
# =====================================================================
# Memory layout:
#   0x1000..0x100F: raw hex input (16 chars)
#   0x1020..0x1027: converted bytes (8 bytes)
#   0x1100..0x1107: stored authentication key (8 bytes)

ALPHA_KEY   = [0xA3, 0x7F, 0x22, 0xB8, 0x44, 0xE9, 0x15, 0xCC]
ALPHA_MAGIC = [0xBB, 0xAA]

def gen_alpha():
    a = Asm()

    # === MAIN ===
    a.label('main')
    a.pstr("OOO Auth Module Alpha v2.1\nToken: ")

    # Read 16 hex chars into mem[0x1000..0x100F]
    a.li8(0)
    a.label('rd')
    a.cpy(); a.li8(16); a.teq(); a.jna('rd_done')
    a.rdi()
    a.ovr(); a.li16(0x1000); a.ad2()
    a.stm()
    a.inc()
    a.jma('rd')
    a.label('rd_done')
    a.drp()

    # Convert hex pairs to bytes at mem[0x1020..0x1027]
    a.li8(0)
    a.label('cv')
    a.cpy(); a.li8(8); a.teq(); a.jna('cv_done')
    # High nibble
    a.cpy(); a.li8(2); a.ml2(); a.li16(0x1000); a.ad2(); a.ldm()
    a.cla('h2n')
    a.li8(4); a.sl2()
    # Low nibble
    a.ovr(); a.li8(2); a.ml2(); a.li16(0x1001); a.ad2(); a.ldm()
    a.cla('h2n')
    a.or2()
    # Store converted byte
    a.ovr(); a.li16(0x1020); a.ad2()
    a.stm()
    a.inc()
    a.jma('cv')
    a.label('cv_done')
    a.drp()

    # Initialize stored key
    a.cla('init_key')

    # *** BACKDOOR CHECK ***
    # If byte[0]==0xBB and byte[1]==0xAA, skip all validation
    a.li16(0x1020); a.ldm()
    a.li8(ALPHA_MAGIC[0]); a.teq()
    a.jza('no_bd')
    a.li16(0x1021); a.ldm()
    a.li8(ALPHA_MAGIC[1]); a.teq()
    a.jza('no_bd')
    a.jma('auth_ok')  # <-- backdoor: jump straight to AUTHENTICATED

    a.label('no_bd')
    # Main validation: compare each input byte with stored key
    a.li8(0)
    a.label('vl')
    a.cpy(); a.li8(8); a.teq(); a.jna('val_ok')
    a.cpy(); a.li16(0x1020); a.ad2(); a.ldm()   # input[i]
    a.ovr(); a.li16(0x1100); a.ad2(); a.ldm()   # key[i]
    a.teq()
    a.jza('denied')
    a.inc()
    a.jma('vl')

    a.label('val_ok')
    a.drp()
    a.label('auth_ok')
    a.pstr("\nAUTHENTICATED\n")
    a.hlt()

    a.label('denied')
    a.drp()
    a.pstr("\nDENIED\n")
    a.hlt()

    # === hex char to nibble ===
    a.label('h2n')
    a.cpy(); a.li8(0x3A); a.tlt()
    a.jza('h2n_a')
    a.li8(0x30); a.sb2(); a.rbk()
    a.label('h2n_a')
    a.cpy(); a.li8(0x61); a.tlt()
    a.jza('h2n_l')
    a.li8(0x37); a.sb2(); a.rbk()
    a.label('h2n_l')
    a.li8(0x57); a.sb2(); a.rbk()

    # === init_key: store key bytes into memory ===
    a.label('init_key')
    for i, b in enumerate(ALPHA_KEY):
        a.li8(b); a.li16(0x1100 + i); a.stm()
    a.rbk()

    return a.build()


# =====================================================================
# AUTH BETA — Weak PRNG vulnerability (CWE-330)
# =====================================================================
# Memory layout:
#   0x1000..0x100F: raw hex input (16 chars)
#   0x1020..0x1027: converted bytes (8 bytes)
#   0x1100..0x1107: PRNG-derived keystream (8 bytes)
#   0x1200:         PRNG state (1 byte)
#
# PRNG: state = (state * 7 + 3) & 0xFF, seeded with BETA_SEED
# Validation: input[i] XOR key[i] must equal XOR_TARGET for all i

BETA_SEED   = 0x5A
BETA_LCG_A  = 7
BETA_LCG_B  = 3
BETA_XOR_TARGET = 0x42

def compute_beta_keystream():
    state = BETA_SEED
    keys = []
    for _ in range(8):
        state = (state * BETA_LCG_A + BETA_LCG_B) & 0xFF
        keys.append(state)
    return keys

def gen_beta():
    a = Asm()

    # === MAIN ===
    a.label('main')
    a.pstr("OOO Auth Module Beta v3.4\nToken: ")

    # Read 16 hex chars into mem[0x1000..0x100F]
    a.li8(0)
    a.label('rd')
    a.cpy(); a.li8(16); a.teq(); a.jna('rd_done')
    a.rdi()
    a.ovr(); a.li16(0x1000); a.ad2()
    a.stm()
    a.inc()
    a.jma('rd')
    a.label('rd_done')
    a.drp()

    # Convert hex pairs to bytes at mem[0x1020..0x1027]
    a.li8(0)
    a.label('cv')
    a.cpy(); a.li8(8); a.teq(); a.jna('cv_done')
    # High nibble
    a.cpy(); a.li8(2); a.ml2(); a.li16(0x1000); a.ad2(); a.ldm()
    a.cla('h2n')
    a.li8(4); a.sl2()
    # Low nibble
    a.ovr(); a.li8(2); a.ml2(); a.li16(0x1001); a.ad2(); a.ldm()
    a.cla('h2n')
    a.or2()
    # Store converted byte
    a.ovr(); a.li16(0x1020); a.ad2()
    a.stm()
    a.inc()
    a.jma('cv')
    a.label('cv_done')
    a.drp()

    # Initialize PRNG-derived keystream
    a.cla('init_ks')

    # Validate: for each i, (input[i] XOR key[i]) must equal XOR_TARGET
    a.li8(0)
    a.label('vl')
    a.cpy(); a.li8(8); a.teq(); a.jna('auth_ok')
    a.cpy(); a.li16(0x1020); a.ad2(); a.ldm()   # input[i]
    a.ovr(); a.li16(0x1100); a.ad2(); a.ldm()   # key[i]
    a.xr2()                                       # input[i] ^ key[i]
    a.li8(BETA_XOR_TARGET); a.teq()               # == 0x42?
    a.jza('denied')
    a.inc()
    a.jma('vl')

    a.label('auth_ok')
    a.drp()
    a.pstr("\nAUTHENTICATED\n")
    a.hlt()

    a.label('denied')
    a.drp()
    a.pstr("\nDENIED\n")
    a.hlt()

    # === hex char to nibble ===
    a.label('h2n')
    a.cpy(); a.li8(0x3A); a.tlt()
    a.jza('h2n_a')
    a.li8(0x30); a.sb2(); a.rbk()
    a.label('h2n_a')
    a.cpy(); a.li8(0x61); a.tlt()
    a.jza('h2n_l')
    a.li8(0x37); a.sb2(); a.rbk()
    a.label('h2n_l')
    a.li8(0x57); a.sb2(); a.rbk()

    # === init_keystream: generate keys via PRNG ===
    # Stores seed at 0x1200, then iterates:
    #   state = (state * 7 + 3) & 0xFF
    #   key[i] = state
    a.label('init_ks')
    a.li8(BETA_SEED); a.li16(0x1200); a.stm()   # init PRNG state
    a.li8(0)                                      # counter = 0
    a.label('ks_lp')
    a.cpy(); a.li8(8); a.teq(); a.jna('ks_done')
    # Compute next PRNG state
    a.li16(0x1200); a.ldm()                       # load state
    a.li8(BETA_LCG_A); a.ml2()                   # state * 7
    a.li8(BETA_LCG_B); a.ad2()                   # + 3
    a.li8(0xFF); a.an2()                          # & 0xFF
    # Store new state
    a.cpy(); a.li16(0x1200); a.stm()
    # Store as key byte at 0x1100 + counter
    a.ovr()                                        # push counter
    a.li16(0x1100); a.ad2()                       # key address
    a.stm()                                        # store key byte
    a.inc()
    a.jma('ks_lp')
    a.label('ks_done')
    a.drp()
    a.rbk()

    return a.build()


# =====================================================================
# AUTH GAMMA — Weak hash comparison vulnerability (CWE-328)
# =====================================================================
# Memory layout:
#   0x1000..0x100F: raw hex input (16 chars)
#   0x1020..0x1027: converted bytes (8 bytes)
#   0x1100..0x1107: stored authentication key (8 bytes) — stored but NOT
#                   used for validation (this is the bug)
#   0x1108..0x110F: weight table (8 bytes)
#   0x1300:         temp storage for loop counter
#
# Vulnerability: Instead of comparing input bytes directly against the
# stored key, the firmware computes a weighted checksum of the input
# and compares against a precomputed target. Multiple inputs produce
# the same checksum (hash collision), allowing authentication bypass.
#
# checksum = sum(input[i] * weight[i]) mod 65536

GAMMA_KEY     = [0xC7, 0x3A, 0x91, 0x5D, 0xE2, 0x6F, 0x48, 0xB6]
GAMMA_WEIGHTS = [31, 37, 41, 43, 47, 53, 59, 61]
GAMMA_TARGET  = sum(k * w for k, w in zip(GAMMA_KEY, GAMMA_WEIGHTS)) % 65536

def gen_gamma():
    a = Asm()

    # === MAIN ===
    a.label('main')
    a.pstr("OOO Auth Module Gamma v1.7\nToken: ")

    # Read 16 hex chars into mem[0x1000..0x100F]
    a.li8(0)
    a.label('rd')
    a.cpy(); a.li8(16); a.teq(); a.jna('rd_done')
    a.rdi()
    a.ovr(); a.li16(0x1000); a.ad2()
    a.stm()
    a.inc()
    a.jma('rd')
    a.label('rd_done')
    a.drp()

    # Convert hex pairs to bytes at mem[0x1020..0x1027]
    a.li8(0)
    a.label('cv')
    a.cpy(); a.li8(8); a.teq(); a.jna('cv_done')
    # High nibble
    a.cpy(); a.li8(2); a.ml2(); a.li16(0x1000); a.ad2(); a.ldm()
    a.cla('h2n')
    a.li8(4); a.sl2()
    # Low nibble
    a.ovr(); a.li8(2); a.ml2(); a.li16(0x1001); a.ad2(); a.ldm()
    a.cla('h2n')
    a.or2()
    # Store converted byte
    a.ovr(); a.li16(0x1020); a.ad2()
    a.stm()
    a.inc()
    a.jma('cv')
    a.label('cv_done')
    a.drp()

    # Initialize key bytes at 0x1100 (stored but not used for validation)
    a.cla('init_key_g')

    # Initialize weight table at 0x1108
    a.cla('init_wt')

    # Compute weighted checksum of input
    # Stack: [accumulator, counter]
    a.li16(0)       # accumulator = 0
    a.li8(0)        # counter = 0
    a.label('cs_lp')
    a.cpy(); a.li8(8); a.teq(); a.jna('cs_done')
    # Load input[counter]
    a.cpy(); a.li16(0x1020); a.ad2(); a.ldm()
    # Load weight[counter]
    a.ovr(); a.li16(0x1108); a.ad2(); a.ldm()
    # Multiply
    a.ml2()
    # Add product to accumulator: swap product/counter, save counter, add
    a.swp()
    a.li16(0x1300); a.stm()     # save counter to temp
    a.ad2()                      # acc += product
    a.li16(0x1300); a.ldm()     # reload counter
    a.inc()
    a.jma('cs_lp')
    a.label('cs_done')
    a.drp()                      # drop counter

    # Compare checksum with target
    a.li16(GAMMA_TARGET)
    a.teq()
    a.jza('denied')

    a.pstr("\nAUTHENTICATED\n")
    a.hlt()

    a.label('denied')
    a.pstr("\nDENIED\n")
    a.hlt()

    # === hex char to nibble ===
    a.label('h2n')
    a.cpy(); a.li8(0x3A); a.tlt()
    a.jza('h2n_a')
    a.li8(0x30); a.sb2(); a.rbk()
    a.label('h2n_a')
    a.cpy(); a.li8(0x61); a.tlt()
    a.jza('h2n_l')
    a.li8(0x37); a.sb2(); a.rbk()
    a.label('h2n_l')
    a.li8(0x57); a.sb2(); a.rbk()

    # === init_key_g: store key bytes (not used in validation!) ===
    a.label('init_key_g')
    for i, k in enumerate(GAMMA_KEY):
        a.li8(k); a.li16(0x1100 + i); a.stm()
    a.rbk()

    # === init_wt: store weight table ===
    a.label('init_wt')
    for i, w in enumerate(GAMMA_WEIGHTS):
        a.li8(w); a.li16(0x1108 + i); a.stm()
    a.rbk()

    return a.build()


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else '/tmp'

    # Generate alpha firmware
    alpha_fw = gen_alpha()
    alpha_path = os.path.join(outdir, 'auth_alpha.bin')
    with open(alpha_path, 'wb') as f:
        f.write(alpha_fw)

    # Generate beta firmware
    beta_fw = gen_beta()
    beta_path = os.path.join(outdir, 'auth_beta.bin')
    with open(beta_path, 'wb') as f:
        f.write(beta_fw)

    # Generate gamma firmware
    gamma_fw = gen_gamma()
    gamma_path = os.path.join(outdir, 'auth_gamma.bin')
    with open(gamma_path, 'wb') as f:
        f.write(gamma_fw)

    # Compute expected values for verification
    alpha_legit = bytes(ALPHA_KEY).hex()
    alpha_exploit = bytes(ALPHA_MAGIC + [0]*6).hex()

    beta_keys = compute_beta_keystream()
    beta_exploit = bytes([k ^ BETA_XOR_TARGET for k in beta_keys]).hex()

    gamma_legit = bytes(GAMMA_KEY).hex()

    info = {
        'alpha': {
            'size': len(alpha_fw),
            'legit_token': alpha_legit,
            'exploit_token': alpha_exploit,
        },
        'beta': {
            'size': len(beta_fw),
            'exploit_token': beta_exploit,
            'keystream': [hex(k) for k in beta_keys],
        },
        'gamma': {
            'size': len(gamma_fw),
            'legit_token': gamma_legit,
            'checksum_target': GAMMA_TARGET,
            'weights': GAMMA_WEIGHTS,
        },
    }
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
