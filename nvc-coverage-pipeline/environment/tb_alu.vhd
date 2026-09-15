-- tb_alu.vhd: Testbench for parameterized ALU
--

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_alu is
    generic (
        WIDTH : positive := 8
    );
end entity;

architecture test of tb_alu is

    signal a, b, result : std_logic_vector(WIDTH-1 downto 0);
    signal op           : std_logic_vector(3 downto 0);
    signal zero, carry, ovf, neg : std_logic;

    constant OP_ADD : std_logic_vector(3 downto 0) := "0000";
    constant OP_SUB : std_logic_vector(3 downto 0) := "0001";

begin

    dut: entity work.alu
        generic map (WIDTH => WIDTH)
        port map (
            a => a, b => b, op => op,
            result => result, zero => zero,
            carry => carry, ovf => ovf, neg => neg
        );

    stim: process
    begin
        -- Test ADD: 3 + 5 = 8
        a <= std_logic_vector(to_unsigned(3, WIDTH));
        b <= std_logic_vector(to_unsigned(5, WIDTH));
        op <= OP_ADD;
        wait for 10 ns;
        assert unsigned(result) = 8
            report "ADD 3+5 failed, got " & integer'image(to_integer(unsigned(result)))
            severity failure;
        assert zero = '0'
            report "ADD zero flag wrong" severity failure;

        -- Test ADD: 0 + 0 = 0 (zero flag)
        a <= (others => '0');
        b <= (others => '0');
        op <= OP_ADD;
        wait for 10 ns;
        assert unsigned(result) = 0
            report "ADD 0+0 failed" severity failure;
        assert zero = '1'
            report "Zero flag not set for 0+0" severity failure;

        -- Test SUB: 10 - 3 = 7
        a <= std_logic_vector(to_unsigned(10, WIDTH));
        b <= std_logic_vector(to_unsigned(3, WIDTH));
        op <= OP_SUB;
        wait for 10 ns;
        assert unsigned(result) = 7
            report "SUB 10-3 failed" severity failure;

        report "Basic tests passed" severity note;
        wait;
    end process;

end architecture;
