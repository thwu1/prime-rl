# debug_keccak.gdb - GDB helper for debugging Keccak-f[1600]
#
# Usage:
#   make debug_test
#   gdb -x debug_keccak.gdb ./debug_test
#
# Provides commands for inspecting the 5x5 state array at each step
# of the permutation. Compare values against NIST FIPS 202 examples.

set print elements 0
set pagination off

# Break at the entry of the permutation function
break keccak_f1600

# Custom command: print the full 5x5 state array as hex lanes
define pstate
  printf "=== Keccak State [5][5] ===\n"
  set $px = 0
  while $px < 5
    set $py = 0
    while $py < 5
      printf "  state[%d][%d] = 0x%016lx\n", $px, $py, state[$px][$py]
      set $py = $py + 1
    end
    set $px = $px + 1
  end
end

# Custom command: print the D array from theta step
define ptheta_d
  printf "=== Theta D[5] ===\n"
  set $pi = 0
  while $pi < 5
    printf "  D[%d] = 0x%016lx\n", $pi, D[$pi]
    set $pi = $pi + 1
  end
end

# Custom command: print the C column parity array
define ptheta_c
  printf "=== Theta C[5] (column parities) ===\n"
  set $pi = 0
  while $pi < 5
    printf "  C[%d] = 0x%016lx\n", $pi, C[$pi]
    set $pi = $pi + 1
  end
end

# Custom command: print current round index
define pround
  printf "Round: %d\n", round_idx
end

document pstate
Print the 5x5 Keccak state array as 64-bit hex lanes.
Use after stopping inside keccak_f1600().
end

document ptheta_d
Print the D[5] array computed during the theta step.
end

document ptheta_c
Print the C[5] column parity array from the theta step.
end

document pround
Print the current round index (0-23).
end

run
