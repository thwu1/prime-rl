-- verify_shift.vhd: Verify that SHL/SHR work with shift amounts > 15
--

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity verify_shift is
end entity;

architecture test of verify_shift is
    signal a, b, result : std_logic_vector(31 downto 0);
    signal op           : std_logic_vector(3 downto 0);
    signal zero, carry, ovf, neg : std_logic;
begin
    dut: entity work.alu
        generic map (WIDTH => 32)
        port map (
            a => a, b => b, op => op,
            result => result, zero => zero,
            carry => carry, ovf => ovf, neg => neg
        );

    process
    begin
        -- SHL: 1 << 16 must equal 65536
        -- With the b(3 downto 0) bug, b=16 (0x10) truncates to 0 → result=1
        a <= x"00000001";
        b <= x"00000010";   -- 16
        op <= "0101";        -- OP_SHL
        wait for 10 ns;
        assert unsigned(result) = 65536
            report "SHL BUG: 1 << 16 should be 65536, got " &
                   integer'image(to_integer(unsigned(result)))
            severity failure;

        -- SHL: 1 << 24 must equal 16777216
        a <= x"00000001";
        b <= x"00000018";   -- 24
        op <= "0101";
        wait for 10 ns;
        assert unsigned(result) = 16777216
            report "SHL BUG: 1 << 24 should be 16777216, got " &
                   integer'image(to_integer(unsigned(result)))
            severity failure;

        -- SHR: 2^20 >> 20 must equal 1
        a <= x"00100000";   -- 1048576 = 2^20
        b <= x"00000014";   -- 20
        op <= "0110";        -- OP_SHR
        wait for 10 ns;
        assert unsigned(result) = 1
            report "SHR BUG: 2^20 >> 20 should be 1, got " &
                   integer'image(to_integer(unsigned(result)))
            severity failure;

        report "Shift verification passed" severity note;
        wait;
    end process;
end architecture;
