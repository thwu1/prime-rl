-- verify_ovf.vhd: Verify that SUB overflow flag is computed correctly
--

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity verify_ovf is
end entity;

architecture test of verify_ovf is
    signal a, b, result : std_logic_vector(7 downto 0);
    signal op           : std_logic_vector(3 downto 0);
    signal zero, carry, ovf, neg : std_logic;
begin
    dut: entity work.alu
        generic map (WIDTH => 8)
        port map (
            a => a, b => b, op => op,
            result => result, zero => zero,
            carry => carry, ovf => ovf, neg => neg
        );

    process
    begin
        -- SUB: 0x80 - 0x01
        -- Signed interpretation: -128 - 1 = -129, which overflows to +127
        -- The overflow flag MUST be '1'
        a <= x"80";
        b <= x"01";
        op <= "0001";   -- OP_SUB
        wait for 10 ns;
        assert ovf = '1'
            report "OVF BUG: SUB 0x80-0x01 should set overflow, got ovf=" &
                   std_logic'image(ovf)
            severity failure;
        assert unsigned(result) = 127
            report "SUB 0x80-0x01 result should be 127"
            severity failure;

        -- SUB: 0x7F - 0xFF
        -- Signed: +127 - (-1) = +128, overflows to -128
        -- Overflow flag MUST be '1'
        a <= x"7F";
        b <= x"FF";
        op <= "0001";
        wait for 10 ns;
        assert ovf = '1'
            report "OVF BUG: SUB 0x7F-0xFF should set overflow, got ovf=" &
                   std_logic'image(ovf)
            severity failure;

        -- SUB: 0x05 - 0x03 = 2 (no overflow)
        a <= x"05";
        b <= x"03";
        op <= "0001";
        wait for 10 ns;
        assert ovf = '0'
            report "OVF BUG: SUB 5-3 should NOT set overflow"
            severity failure;

        report "Overflow verification passed" severity note;
        wait;
    end process;
end architecture;
