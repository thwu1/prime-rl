#!/usr/bin/env python3
"""
Fix bugs in the C source, fix the Makefile, and build the shared library.

"""
import os
import subprocess

SRC_DIR = "/app/src"

def fix_c_source():
    path = os.path.join(SRC_DIR, "if97_core.c")
    with open(path, "r") as f:
        code = f.read()

    # Bug 1: Region 1 coefficient n[5] has wrong sign (negative, should be positive)
    code = code.replace("-0.15772038513228e+00", " 0.15772038513228e+00", 1)

    # Bug 2: Saturation PSat_T uses exponent 3, should be 4
    code = code.replace("pow(val, 3)", "pow(val, 4)", 1)

    with open(path, "w") as f:
        f.write(code)


def fix_makefile():
    path = os.path.join(SRC_DIR, "Makefile")
    makefile = (
        "CC = gcc\n"
        "CFLAGS = -O2 -Wall -fPIC\n"
        "\n"
        "all: libif97.so\n"
        "\n"
        "if97_core.o: if97_core.c if97_core.h\n"
        "\t$(CC) $(CFLAGS) -c if97_core.c -o if97_core.o\n"
        "\n"
        "libif97.so: if97_core.o\n"
        "\t$(CC) -shared -o libif97.so if97_core.o -lm\n"
        "\n"
        "clean:\n"
        "\trm -f *.o *.so *.a\n"
    )
    with open(path, "w") as f:
        f.write(makefile)


def build():
    subprocess.run(["make", "clean"], cwd=SRC_DIR, check=True)
    subprocess.run(["make"], cwd=SRC_DIR, check=True)


if __name__ == "__main__":
    fix_c_source()
    fix_makefile()
    build()
