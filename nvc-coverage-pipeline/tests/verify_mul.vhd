-- verify_mul.vhd: Verify that MUL carry detects overflow in all upper product bits
--

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity verify_mul is
end entity;

architecture test of verify_mul is
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
        -- MUL: 64 * 8 = 512 = 0x0200
        -- Upper byte = 0x02, but bit 8 = '0'
        -- carry must be '1' because product exceeds 8 bits
        a <= x"40";   -- 64
        b <= x"08";   -- 8
        op <= "1001";  -- OP_MUL
        wait for 10 ns;
        assert carry = '1'
            report "MUL CARRY BUG: 64*8=512 overflows 8 bits, carry should be set, got carry=" &
                   std_logic'image(carry)
            severity failure;

        -- MUL: 255 * 3 = 765 = 0x02FD
        -- Upper byte = 0x02, but bit 8 = '0'
        -- carry must be '1'
        a <= x"FF";   -- 255
        b <= x"03";   -- 3
        op <= "1001";
        wait for 10 ns;
        assert carry = '1'
            report "MUL CARRY BUG: 255*3=765 overflows 8 bits, carry should be set, got carry=" &
                   std_logic'image(carry)
            severity failure;

        -- MUL: 3 * 3 = 9 — no overflow, carry must be '0'
        a <= x"03";
        b <= x"03";
        op <= "1001";
        wait for 10 ns;
        assert carry = '0'
            report "MUL carry incorrectly set for 3*3=9"
            severity failure;

        report "MUL carry verification passed" severity note;
        wait;
    end process;
end architecture;
