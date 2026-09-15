use tbmcu001_pac::*;

fn setup() {
    mmio::init();
    Peripherals::reset_singleton();
}

// ──────────────────────────────────────────────
// Singleton
// ──────────────────────────────────────────────

#[test]
fn test_singleton_take_once() {
    setup();
    let p = Peripherals::take();
    assert!(p.is_some(), "First take() must return Some");
}

#[test]
fn test_singleton_take_twice_fails() {
    setup();
    let _p = Peripherals::take().unwrap();
    let p2 = Peripherals::take();
    assert!(p2.is_none(), "Second take() must return None");
}

// ──────────────────────────────────────────────
// GPIOA
// ──────────────────────────────────────────────

#[test]
fn test_gpioa_moder_write_all_output() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOA.moder.write(|w| {
        w.mode0().output()
         .mode1().output()
         .mode2().output()
         .mode3().output()
    });
    // mode0=1(0:1), mode1=1(2:3), mode2=1(4:5), mode3=1(6:7) = 0b01010101
    assert_eq!(mmio::read(0x40005000), 0x55);
}

#[test]
fn test_gpioa_moder_read_fields() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // mode0=Input(0), mode1=Output(1), mode2=Alternate(2), mode3=Analog(3)
    // = 0b11_10_01_00 = 0xE4
    mmio::write(0x40005000, 0xE4);
    let r = p.GPIOA.moder.read();
    assert!(r.mode0().is_input());
    assert!(r.mode1().is_output());
    assert!(r.mode2().is_alternate());
    assert!(r.mode3().is_analog());
    assert_eq!(r.mode0().bits(), 0);
    assert_eq!(r.mode1().bits(), 1);
    assert_eq!(r.mode2().bits(), 2);
    assert_eq!(r.mode3().bits(), 3);
}

#[test]
fn test_gpioa_moder_modify_preserves() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // Write initial: mode0=Output(1), mode1=Analog(3), mode2=Input(0), mode3=Alternate(2)
    p.GPIOA.moder.write(|w| {
        w.mode0().output()
         .mode1().analog()
         .mode2().input()
         .mode3().alternate()
    });
    // 0b10_00_11_01 = 0x8D
    assert_eq!(mmio::read(0x40005000), 0x8D);

    // Modify only mode0 to alternate(2)
    p.GPIOA.moder.modify(|_r, w| w.mode0().alternate());
    // mode0=2, rest preserved: 0b10_00_11_10 = 0x8E
    assert_eq!(mmio::read(0x40005000), 0x8E);
}

#[test]
fn test_gpioa_odr_write_read() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOA.odr.write(|w| w.od0().set_bit().od2().set_bit());
    assert_eq!(mmio::read(0x40005004), 0x05);
    let r = p.GPIOA.odr.read();
    assert_eq!(r.od0().bits(), 1);
    assert_eq!(r.od1().bits(), 0);
    assert_eq!(r.od2().bits(), 1);
    assert_eq!(r.od3().bits(), 0);
}

#[test]
fn test_gpioa_idr_read_only() {
    setup();
    let p = unsafe { Peripherals::steal() };
    mmio::write(0x40005008, 0x0A); // bits 1 and 3
    let r = p.GPIOA.idr.read();
    assert_eq!(r.id0().bits(), 0);
    assert_eq!(r.id1().bits(), 1);
    assert_eq!(r.id2().bits(), 0);
    assert_eq!(r.id3().bits(), 1);
}

#[test]
fn test_gpioa_bsrr_write_only() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOA.bsrr.write(|w| w.bs0().set_bit().br2().set_bit());
    // BS0 at bit 0, BR2 at bit 18
    assert_eq!(mmio::read(0x4000500C), 0x00040001);
}

// ──────────────────────────────────────────────
// GPIOB (derived from GPIOA)
// ──────────────────────────────────────────────

#[test]
fn test_gpiob_inherited_moder() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOB.moder.write(|w| {
        w.mode0().output()
         .mode1().alternate()
    });
    // mode0=1(bits0:1), mode1=2(bits2:3) => 0b1001 = 0x09
    assert_eq!(mmio::read(0x40006000), 0x09);
    let r = p.GPIOB.moder.read();
    assert!(r.mode0().is_output());
    assert!(r.mode1().is_alternate());
}

#[test]
fn test_gpiob_inherited_odr() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOB.odr.write(|w| w.od1().set_bit().od3().set_bit());
    assert_eq!(mmio::read(0x40006004), 0x0A);
}

#[test]
fn test_gpiob_inherited_idr() {
    setup();
    let p = unsafe { Peripherals::steal() };
    mmio::write(0x40006008, 0x05); // bits 0 and 2
    let r = p.GPIOB.idr.read();
    assert_eq!(r.id0().bits(), 1);
    assert_eq!(r.id1().bits(), 0);
    assert_eq!(r.id2().bits(), 1);
    assert_eq!(r.id3().bits(), 0);
}

#[test]
fn test_gpiob_inherited_bsrr() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOB.bsrr.write(|w| w.bs1().set_bit().br3().set_bit());
    // BS1 at bit 1, BR3 at bit 19
    assert_eq!(mmio::read(0x4000600C), 0x00080002);
}

#[test]
fn test_gpiob_afrl_write_read() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOB.afrl.write(|w| w.af0().bits(5).af1().bits(7));
    // AF0=5 at bits[0:3], AF1=7 at bits[4:7] => 5 | (7<<4) = 0x75
    assert_eq!(mmio::read(0x40006010), 0x75);
    let r = p.GPIOB.afrl.read();
    assert_eq!(r.af0().bits(), 5);
    assert_eq!(r.af1().bits(), 7);
    assert_eq!(r.af2().bits(), 0);
    assert_eq!(r.af3().bits(), 0);
}

#[test]
fn test_gpiob_afrl_modify() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.GPIOB.afrl.write(|w| w.af0().bits(3).af2().bits(9));
    // AF0=3(bits0:3), AF2=9(bits8:11) => 3 | (9<<8) = 0x903
    assert_eq!(mmio::read(0x40006010), 0x903);
    p.GPIOB.afrl.modify(|_r, w| w.af1().bits(15));
    // AF0=3, AF1=15(bits4:7), AF2=9 preserved => 3 | (15<<4) | (9<<8) = 0x9F3
    assert_eq!(mmio::read(0x40006010), 0x9F3);
}

#[test]
fn test_gpiob_independent_of_gpioa() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // Write to GPIOA.MODER
    p.GPIOA.moder.write(|w| w.mode0().analog());
    // Write to GPIOB.MODER
    p.GPIOB.moder.write(|w| w.mode0().output());
    // Verify they are independent (different base addresses)
    assert_eq!(mmio::read(0x40005000), 0x03); // GPIOA: analog=3
    assert_eq!(mmio::read(0x40006000), 0x01); // GPIOB: output=1
}

// ──────────────────────────────────────────────
// SPI1
// ──────────────────────────────────────────────

#[test]
fn test_spi1_cr1_write_mode() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.SPI1.cr1.write(|w| {
        w.cpha().second_edge()
         .cpol().idle_high()
         .mstr().master()
         .br().div8()
         .spe().set_bit()
         .dff().sixteen()
    });
    // CPHA=1(0), CPOL=1(1), MSTR=1(2), BR=2(3:5), SPE=1(6), DFF=1(11)
    let expected = (1 << 0) | (1 << 1) | (1 << 2) | (2 << 3) | (1 << 6) | (1 << 11);
    assert_eq!(mmio::read(0x40008000), expected);
}

#[test]
fn test_spi1_cr1_read_fields() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // CPOL=IdleHigh(bit1), BR=Div64(5 at bits3:5), LSBFIRST=LsbFirst(bit7)
    let val = (1 << 1) | (5 << 3) | (1 << 7);
    mmio::write(0x40008000, val);
    let r = p.SPI1.cr1.read();
    assert!(r.cpol().is_idle_high());
    assert!(r.br().is_div64());
    assert!(r.lsbfirst().is_lsb_first());
    assert!(r.cpha().is_first_edge());
    assert!(r.mstr().is_slave());
}

#[test]
fn test_spi1_sr_read_only_reset() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // SR has reset value 0x02 (TXE=1 at bit1)
    let r = p.SPI1.sr.read();
    assert_eq!(r.txe().bits(), 1);
    assert_eq!(r.rxne().bits(), 0);
    assert_eq!(r.bsy().bits(), 0);
}

#[test]
fn test_spi1_dr_roundtrip() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.SPI1.dr.write(|w| w.dr().bits(0xABCD));
    let r = p.SPI1.dr.read();
    assert_eq!(r.dr().bits(), 0xABCD);
}

#[test]
fn test_spi1_cr2_individual_bits() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.SPI1.cr2.write(|w| {
        w.rxdmaen().set_bit()
         .txeie().set_bit()
         .ssoe().set_bit()
    });
    // RXDMAEN=1(bit0), SSOE=1(bit2), TXEIE=1(bit7) = 0x85
    assert_eq!(mmio::read(0x40008004), 0x85);
}

// ──────────────────────────────────────────────
// TIM2
// ──────────────────────────────────────────────

#[test]
fn test_tim2_cr1_direction_modes() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.cr1.write(|w| {
        w.cen().set_bit()
         .dir().down()
         .cms().center_aligned2()
         .arpe().set_bit()
    });
    // CEN=1(0), DIR=1(4), CMS=2(5:6), ARPE=1(7)
    let expected = (1 << 0) | (1 << 4) | (2 << 5) | (1 << 7);
    assert_eq!(mmio::read(0x40000000), expected);

    let r = p.TIM2.cr1.read();
    assert!(r.dir().is_down());
    assert!(r.cms().is_center_aligned2());
}

#[test]
fn test_tim2_arr_reset_value() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // ARR has reset value 0x0000FFFF
    let r = p.TIM2.arr.read();
    assert_eq!(r.arr().bits(), 0x0000FFFF);
}

#[test]
fn test_tim2_egr_write_only() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.egr.write(|w| w.ug().set_bit());
    assert_eq!(mmio::read(0x40000014), 0x01);
}

#[test]
fn test_tim2_psc_write_read() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.psc.write(|w| w.psc().bits(7999));
    let r = p.TIM2.psc.read();
    assert_eq!(r.psc().bits(), 7999);
}

#[test]
fn test_tim2_cnt_large_value() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.cnt.write(|w| w.cnt().bits(0xDEADBEEF));
    let r = p.TIM2.cnt.read();
    assert_eq!(r.cnt().bits(), 0xDEADBEEF);
}

#[test]
fn test_tim2_sr_modify_clear_flag() {
    setup();
    let p = unsafe { Peripherals::steal() };
    mmio::write(0x40000010, 0x07); // UIF=1, CC1IF=1, CC2IF=1
    let r = p.TIM2.sr.read();
    assert_eq!(r.uif().bits(), 1);
    assert_eq!(r.cc1if().bits(), 1);

    // Clear only UIF, preserve others
    p.TIM2.sr.modify(|_r, w| w.uif().clear_bit());
    let r2 = p.TIM2.sr.read();
    assert_eq!(r2.uif().bits(), 0);
    assert_eq!(r2.cc1if().bits(), 1);
}

// ──────────────────────────────────────────────
// TIM2 CCR register array (dim-expanded)
// ──────────────────────────────────────────────

#[test]
fn test_tim2_ccr_array_write_read() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.ccr1.write(|w| w.ccr().bits(1000));
    p.TIM2.ccr2.write(|w| w.ccr().bits(2000));
    p.TIM2.ccr3.write(|w| w.ccr().bits(3000));
    p.TIM2.ccr4.write(|w| w.ccr().bits(4000));
    assert_eq!(p.TIM2.ccr1.read().ccr().bits(), 1000);
    assert_eq!(p.TIM2.ccr2.read().ccr().bits(), 2000);
    assert_eq!(p.TIM2.ccr3.read().ccr().bits(), 3000);
    assert_eq!(p.TIM2.ccr4.read().ccr().bits(), 4000);
}

#[test]
fn test_tim2_ccr_array_addresses() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.ccr1.write(|w| w.ccr().bits(0xAA));
    p.TIM2.ccr2.write(|w| w.ccr().bits(0xBB));
    p.TIM2.ccr3.write(|w| w.ccr().bits(0xCC));
    p.TIM2.ccr4.write(|w| w.ccr().bits(0xDD));
    // CCR1 at base+0x34, CCR2 at base+0x38, CCR3 at base+0x3C, CCR4 at base+0x40
    assert_eq!(mmio::read(0x40000034), 0xAA);
    assert_eq!(mmio::read(0x40000038), 0xBB);
    assert_eq!(mmio::read(0x4000003C), 0xCC);
    assert_eq!(mmio::read(0x40000040), 0xDD);
}

#[test]
fn test_tim2_ccr_modify() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.ccr1.write(|w| w.ccr().bits(0x1234));
    p.TIM2.ccr1.modify(|r, w| {
        let cur = r.ccr().bits();
        w.ccr().bits(cur + 1)
    });
    assert_eq!(p.TIM2.ccr1.read().ccr().bits(), 0x1235);
}

// ──────────────────────────────────────────────
// Cross-cutting behavior
// ──────────────────────────────────────────────

#[test]
fn test_modify_reads_current_value() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.dier.write(|w| w.uie().set_bit().cc1ie().set_bit());
    assert_eq!(mmio::read(0x4000000C), 0x03);

    // Modify: read current, conditionally add CC2IE
    p.TIM2.dier.modify(|r, w| {
        if r.uie().bits() == 1 {
            w.cc2ie().set_bit()
        } else {
            w
        }
    });
    // UIE=1, CC1IE=1 preserved, CC2IE=1 added => 0x07
    assert_eq!(mmio::read(0x4000000C), 0x07);
}

#[test]
fn test_write_uses_reset_not_current() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // First write: set CEN and ARPE
    p.TIM2.cr1.write(|w| w.cen().set_bit().arpe().set_bit());
    assert_eq!(mmio::read(0x40000000), 0x81);

    // Second write: only set DIR — should start from reset (0x0), not current
    p.TIM2.cr1.write(|w| w.dir().down());
    // Only DIR(bit4) should be set; CEN and ARPE are gone
    assert_eq!(mmio::read(0x40000000), 0x10);
}

#[test]
fn test_raw_bits_write() {
    setup();
    let p = unsafe { Peripherals::steal() };
    p.TIM2.cnt.write(|w| unsafe { w.bits(0x12345678) });
    assert_eq!(mmio::read(0x40000024), 0x12345678);
}

#[test]
fn test_register_reset_method() {
    setup();
    let p = unsafe { Peripherals::steal() };
    // Write a non-reset value
    p.TIM2.arr.write(|w| w.arr().bits(0x1234));
    assert_eq!(mmio::read(0x4000002C), 0x1234);
    // Reset should restore to 0xFFFF
    p.TIM2.arr.reset();
    assert_eq!(mmio::read(0x4000002C), 0x0000FFFF);
}
