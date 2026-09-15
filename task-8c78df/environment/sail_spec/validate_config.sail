// =======================================================================================
// This Sail RISC-V architecture model, comprising all files and
// directories except where otherwise noted is subject the BSD
// two-clause license in the LICENSE file.
//
// SPDX-License-Identifier: BSD-2-Clause
// =======================================================================================

private function check_privs() -> bool = {
  if (config extensions.S.supported : bool) & not(config extensions.U.supported : bool)
  then {
    print_endline("User mode (U) should be enabled if supervisor mode (S) is enabled.");
    return false;
  };
  true
}

private function require_Sv32(ext_name : string) -> bool = {
  if not(config extensions.Sv32.supported : bool) then {
    print_endline("The " ^ ext_name ^ " extension is enabled but Sv32 is disabled: " ^ ext_name ^ " depends on Sv32 on RV32.");
    return false;
  };
  true
}

private function require_Sv39(ext_name : string) -> bool = {
  if not(config extensions.Sv39.supported : bool) then {
    print_endline("The " ^ ext_name ^ " extension is enabled but Sv39 is disabled: " ^ ext_name ^ " depends on Sv39 on RV64.");
    return false;
  };
  true
}

private function require_virtual_memory(ext_name : string) -> bool = {
  if xlen == 32 then return require_Sv32(ext_name);

  assert(xlen == 64);
  require_Sv39(ext_name)
}

// This logic will need to change once MXL/SXL/UXL can differ.
private function check_mmu_config() -> bool = {
  var valid : bool = true;
  if xlen == 64 then {
    if not(config extensions.S.supported : bool) & ((config extensions.Sv57.supported : bool) | (config extensions.Sv48.supported : bool) | (config extensions.Sv39.supported : bool))
    then {
      valid = false;
      print_endline("Supervisor mode (S) disabled but one of (Sv57, Sv48, Sv39) is enabled: cannot support address translation without supervisor mode.");
    };
    if (config extensions.Sv57.supported : bool) & not(config extensions.Sv48.supported : bool)
    then {
      valid = false;
      print_endline("Sv57 is enabled but Sv48 is disabled: supporting Sv57 requires supporting Sv48.");
    };
    if (config extensions.Sv48.supported : bool) & not(config extensions.Sv39.supported : bool)
    then {
      valid = false;
      print_endline("Sv48 is enabled but Sv39 is disabled: supporting Sv48 requires supporting Sv39.");
    };
    if (config extensions.Sv32.supported : bool)
    then {
      valid = false;
      print_endline("Sv32 is enabled: Sv32 is not supported on RV64.");
    };
  } else {
    assert(xlen == 32);
    if not(config extensions.S.supported : bool) & (config extensions.Sv32.supported : bool)
    then {
      valid = false;
      print_endline("Supervisor mode (S) is disabled but Sv32 is enabled: cannot support address translation without supervisor mode.");
    };
    if (config extensions.Sv39.supported : bool) | (config extensions.Sv48.supported : bool) |  (config extensions.Sv57.supported : bool)
    then {
      valid = false;
      print_endline("One or more of Sv39/Sv48/Sv57 is enabled: these are not supported on RV32.");
    };
  };

  if (config extensions.Svrsw60t59b.supported : bool) then {
    if xlen == 32 then {
      valid = false;
      print_endline("The Svrsw60t59b extension is enabled: Svrsw60t59b is not supported on RV32");
    } else {
      valid = valid & require_Sv39("Svrsw60t59b");
    }
  };

  if (config extensions.Ssccptr.supported : bool)
  then valid = valid & require_virtual_memory("Ssccptr");

  if (config extensions.Svade.supported : bool)
  then valid = valid & require_virtual_memory("Svade");

  if (config extensions.Svadu.supported : bool)
  then valid = valid & require_virtual_memory("Svadu");

  if (config extensions.Svpbmt.supported : bool) then {
    if xlen == 32 then {
      valid = false;
      print_endline("The Svpbmt extension is enabled: Svpbmt is not supported on RV32");
    } else {
      valid = valid & require_Sv39("Svpbmt");
    }
  };

  if (config extensions.Svnapot.supported : bool) then {
    if xlen == 32 then {
      valid = false;
      print_endline("The Svnapot extension is enabled: Svnapot is not supported on RV32");
    } else {
      valid = valid & require_Sv39("Svnapot");
    }
  };

  if (config extensions.Svvptc.supported : bool)
  then valid = valid & require_virtual_memory("Svvptc");

  valid
}

private function check_vlen_elen() -> bool = {
  // Should this be conditioned on a vector extension being enabled?

  // Due to the `constraint elen_exp <= vlen_exp` the Sail compiler will
  // dead-code eliminate this check without the `: nat` type annotations.
  // Technically it could still eliminate the check even with `: nat`, and
  // by running any code that violates the `constraint` we're invoking UB.
  // However this does work in practice for now so it's probably better
  // than nothing. The proper fix is: https://github.com/rems-project/sail/issues/1387
  if (vlen_exp : nat) < (elen_exp : nat)
  then {
    print_endline("VLEN (set to 2^" ^ dec_str(vlen_exp) ^ ") cannot be less than ELEN (set to 2^" ^ dec_str(elen_exp) ^ ").");
    return false;
  };
  // The above comment about dead code elimination applies here too.
  if (vlen_exp : nat) < 3 | (vlen_exp : nat) > 16
  then {
    print_endline("VLEN set to 2^" ^ dec_str(vlen_exp) ^ " but must be within [2^3, 2^16].");
    return false;
  };
  if (elen_exp : nat) < 3 | (elen_exp : nat) > 16
  then {
    print_endline("ELEN set to 2^" ^ dec_str(elen_exp) ^ " but must be within [2^3, 2^16].");
    return false;
  };
  true
}

private function check_vext_config() -> bool = {
  var valid : bool = true;
  // Standard Vector Extensions
  if vector_support_level >= Integer & (elen_exp : nat) < 5 then {
    valid = false;
    print_endline("Zve*x is enabled but ELEN is 2^" ^ dec_str(elen_exp) ^ ": ELEN must be >= 2^5");
  };
  // Ideally, this parameter should be
  //   let max_index_eew_exp = config extensions.V.max_index_eew_exp : range(3, elen_exp)
  // except that it runs into https://github.com/rems-project/sail/issues/1392
  let max_index_eew = config extensions.V.max_index_eew_exp : nat;
  if max_index_eew > elen_exp then {
    valid = false;
    print_endline("The maximum index EEW is 2^" ^ dec_str(max_index_eew) ^ " but ELEN is 2^" ^ dec_str(elen_exp) ^ ": the index EEW must not exceed ELEN.");
  } else if max_index_eew < 3 then {
    valid = false;
    print_endline("The maximum index EEW is 2^" ^ dec_str(max_index_eew) ^ " but it should be at least 2^3.");
  };
  if vector_support_level >= Float_single & not(config extensions.F.supported : bool) then {
    valid = false;
    print_endline("Zve*f is enabled but F is disabled: supporting Zve*f requires F.");
  };
  if vector_support_level >= Float_double then {
    if (elen_exp : nat) < 6 then {
      valid = false;
      print_endline("Zve*d is enabled but ELEN is 2^" ^ dec_str(elen_exp) ^ ": ELEN must be >= 2^6");
    };
    if not(hartSupports(Ext_D)) then {
      valid = false;
      print_endline("Zve*d is enabled but D is disabled: supporting Zve*d requires D.");
    };
  };
  if hartSupports(Ext_Zve32x) & not(config extensions.Zicsr.supported : bool) then {
    valid = false;
    print_endline("Zve32x is enabled but Zicsr is disabled: supporting Zve32x requires Zicsr.");
  };
  if hartSupports(Ext_Zve32x) & not(hartSupports(Ext_Zvl32b)) then {
    valid = false;
    print_endline("VLEN (set to 2^" ^ dec_str(vlen_exp) ^ ") is below the minimum required for Zve32x (need Zvl32b).");
  };
  if hartSupports(Ext_Zve64x) & not(hartSupports(Ext_Zvl64b)) then {
    valid = false;
    print_endline("VLEN (set to 2^" ^ dec_str(vlen_exp) ^ ") is below the minimum required for Zve64x (need Zvl64b).");
  };
  if vector_support_level >= Full & not(hartSupports(Ext_Zvl128b)) then {
    valid = false;
    print_endline("VLEN (set to 2^" ^ dec_str(vlen_exp) ^ ") is below the minimum required for V (need Zvl128b).");
  };
  if (config extensions.Zvfhmin.supported : bool) & not(hartSupports(Ext_Zve32f)) then {
    valid = false;
    print_endline("Zvfhmin is enabled but Zve32f is disabled: Zvfhmin requires Zve32f.");
  };
  if (config extensions.Zvfh.supported : bool) & (not(hartSupports(Ext_Zve32f)) | not(config extensions.Zfhmin.supported : bool)) then {
    valid = false;
    print_endline("Zvfh is enabled but Zve32f and/or Zfhmin are disabled: Zvfh requires Zve32f and Zfhmin.");
  };
  // Cryptography Extensions: Vector Instructions
  if (config extensions.Zvbb.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvbb is enabled but Zve32x is disabled: Zvbb requires Zve32x.");
  };
  if (config extensions.Zvbc.supported : bool) & not(hartSupports(Ext_Zve64x) | hartSupports(Ext_V)) then {
    valid = false;
    print_endline("Zvbc is enabled but Zve64x and V are disabled: Zvbc requires Zve64x or V.");
  };
  if (config extensions.Zvkb.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvkb is enabled but Zve32x is disabled: Zvkb requires Zve32x.");
  };
  if (config extensions.Zvkg.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvkg is enabled but Zve32x is disabled: Zvkg requires Zve32x.");
  };
  if (config extensions.Zvkned.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvkned is enabled but Zve32x is disabled: Zvkned requires Zve32x.");
  };
  if (config extensions.Zvknha.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvknha is enabled but Zve32x is disabled: Zvknha requires Zve32x.");
  };
  if (config extensions.Zvknhb.supported : bool) & not(hartSupports(Ext_Zve64x) | hartSupports(Ext_V)) then {
    valid = false;
    print_endline("Zvknhb is enabled but Zve64x and V are disabled: Zvknhb requires Zve64x or V.");
  };
  if (config extensions.Zvksed.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvksed is enabled but Zve32x is disabled: Zvksed requires Zve32x.");
  };
  if (config extensions.Zvksh.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvksh is enabled but Zve32x is disabled: Zvksh requires Zve32x.");
  };
  if (config extensions.Zvkt.supported : bool) & not(hartSupports(Ext_Zve32x)) then {
    valid = false;
    print_endline("Zvkt is enabled but Zve32x is disabled: Zvkt requires Zve32x.");
  };
  valid;
}

private function check_pma_region(region : PMA_Region) -> bool = {
  if region.base[pagesize_bits - 1 .. 0] != zeros() then {
    print_endline("Memory region starting at " ^ bits_str(region.base) ^ " does not start on a 4K (page) boundary.");
    return false;
  };
  if region.size[pagesize_bits - 1 .. 0] != zeros() then {
    print_endline("Memory region starting at " ^ bits_str(region.base) ^ " with size " ^ bits_str(region.size) ^ " does not end on a 4K (page) boundary.");
    return false;
  };

  let pma = region.attributes;
  match pma.mem_type {
    MainMemory =>
      if not(pma.readable & pma.writable & pma.read_idempotent & pma.write_idempotent) then {
        print_endline("Memory region starting at " ^ bits_str(region.base) ^ " is marked as " ^ to_str(pma.mem_type) ^ " but is not readable, read-idempotent, writable, and write-idempotent.");
        return false;
      },
    IOMemory =>
      (),
  };
  true
}

private function check_pmp() -> bool = {
  var valid : bool = true;
  if (config memory.pmp.na4_supported : bool) & sys_pmp_grain != 0
  then {
    valid = false;
    print_endline("NA4 is not supported if the PMP grain G is non-zero.");
  };
  if sys_pmp_usable_count > sys_pmp_count
  then {
    valid = false;
    print_endline("The number of usable PMP entries cannot exceed the total number of PMP entries.");
  };
  valid
}

private function check_misc_extension_dependencies() -> bool = {
  var valid : bool = true;
  if (config extensions.Zcf.supported : bool) & xlen == 64 then {
    valid = false;
    print_endline("The Zcf extension is enabled: Zcf is not supported on RV64.");
  };
  if (config extensions.F.supported : bool) & (config extensions.Zfinx.supported : bool) then {
    valid = false;
    print_endline("The F and Zfinx extensions are mutually exclusive and cannot be supported simultaneously.");
  };
  if (config extensions.Zabha.supported : bool) & not((config extensions.Zaamo.supported : bool) | (config extensions.A.supported : bool)) then {
    valid = false;
    print_endline("The Zabha extension is enabled but Zaamo and A are disabled: supporting Zabha requires Zaamo or A.");
  };
  if (config extensions.Zacas.supported : bool) & not((config extensions.Zaamo.supported : bool) | (config extensions.A.supported : bool)) then {
    valid = false;
    print_endline("The Zacas extension is enabled but Zaamo and A are disabled: supporting Zacas requires Zaamo or A.");
  };
  if (config extensions.Zfinx.supported : bool) & not(config extensions.Zicsr.supported : bool) then {
    valid = false;
    print_endline("The Zfinx extensions is enabled but Zicsr is disabled: supporting Zfinx requires Zicsr.");
  };
  if (config extensions.Zdinx.supported : bool) & not(config extensions.Zfinx.supported : bool) then {
    valid = false;
    print_endline("The Zdinx extensions is enabled but Zfinx is disabled: supporting Zdinx requires Zfinx.");
  };
  if (config extensions.Zhinx.supported : bool) & not(config extensions.Zfinx.supported : bool) then {
    valid = false;
    print_endline("The Zhinx extensions is enabled but Zfinx is disabled: supporting Zhinx requires Zfinx.");
  };
  if (config extensions.Zhinxmin.supported : bool) & not(config extensions.Zfinx.supported : bool) then {
    valid = false;
    print_endline("The Zhinxmin extensions is enabled but Zfinx is disabled: supporting Zhinxmin requires Zfinx.");
  };
  if (config extensions.Zicfilp.supported : bool) & not(config extensions.Zicsr.supported : bool) then {
    valid = false;
    print_endline("The Zicfilp extension is enabled but Zicsr is disabled: supporting Zicfilp requires Zicsr.");
  };
  if (config extensions.Zicfiss.supported : bool) & not((config extensions.Zicsr.supported : bool) & (config extensions.Zimop.supported : bool) & ((config extensions.Zaamo.supported : bool) | (config extensions.A.supported : bool))) then {
    valid = false;
    print_endline("The Zicfiss extension is enabled but one or more of Zicsr, Zimop and (Zaamo or A) are disabled: supporting Zicfiss requires Zicsr, Zimop and (Zaamo or A).");
  };
  if (config extensions.Zfbfmin.supported : bool) & not(config extensions.F.supported : bool) then {
    valid = false;
    print_endline("The Zfbfmin extension is enabled but F is disabled: supporting Zfbfmin requires F.");
  };
  if (config extensions.Zvfbfmin.supported : bool) & not(hartSupports(Ext_Zve32f)) then {
    valid = false;
    print_endline("The Zvfbfmin extension is enabled but Zve32f is disabled: supporting Zvfbfmin requires Zve32f.")
  };
  if (config extensions.Zvfbfwma.supported : bool) & (not(config extensions.Zfbfmin.supported : bool) | not(config extensions.Zvfbfmin.supported : bool)) then {
    valid = false;
    print_endline("The Zvfbfwma extension is enabled but either Zfbfmin or Zvfbfmin is disabled: supporting Zvfbfwma requires Zfbfmin and Zvfbfmin.")
  };
  if (config extensions.Ssqosid.supported : bool) & not(config extensions.Zicsr.supported : bool) then {
    valid = false;
    print_endline("The Ssqosid extension is enabled but Zicsr is disabled: supporting Ssqosid requires Zicsr.");
  };
  valid
}

private function check_extension_param_constraints() -> bool = {
  var valid : bool = true;
  if (config extensions.Zic64b.supported : bool) & (plat_cache_block_size_exp != 6) then {
    valid = false;
    print_endline("The Zic64b extension is enabled but the cache block size is not 64 bytes.");
  };
  let min_rss_exp = log2_xlen - 3;
  if ((config extensions.A.supported : bool) | (config extensions.Zalrsc.supported : bool)) & (plat_reservation_set_size_exp < min_rss_exp) then {
    valid = false;
    print_endline("The A or Zalrsc extensions are enabled, but the reservation set size of 2^" ^ dec_str(plat_reservation_set_size_exp) ^
                  " is too small; it should be at least 2^" ^ dec_str(min_rss_exp) ^
                  " for the LR/SC operands on this platform.");
  };
  valid
}

function config_is_valid() -> bool = {
    check_privs()
  & check_mmu_config()
  & check_vlen_elen()
  & check_vext_config()
  & check_pmp()
  & check_misc_extension_dependencies()
  & check_extension_param_constraints()
}
