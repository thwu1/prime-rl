-- alu.vhd: Parameterized Arithmetic Logic Unit
-- Supports 10 operations with status flag outputs
--

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity alu is
    generic (
        WIDTH : positive := 8
    );
    port (
        a      : in  std_logic_vector(WIDTH-1 downto 0);
        b      : in  std_logic_vector(WIDTH-1 downto 0);
        op     : in  std_logic_vector(3 downto 0);
        result : out std_logic_vector(WIDTH-1 downto 0);
        zero   : out std_logic;
        carry  : out std_logic;
        ovf    : out std_logic;
        neg    : out std_logic
    );
end entity;

architecture rtl of alu is

    constant OP_ADD : std_logic_vector(3 downto 0) := "0000";
    constant OP_SUB : std_logic_vector(3 downto 0) := "0001";
    constant OP_AND : std_logic_vector(3 downto 0) := "0010";
    constant OP_OR  : std_logic_vector(3 downto 0) := "0011";
    constant OP_XOR : std_logic_vector(3 downto 0) := "0100";
    constant OP_SHL : std_logic_vector(3 downto 0) := "0101";
    constant OP_SHR : std_logic_vector(3 downto 0) := "0110";
    constant OP_NOT : std_logic_vector(3 downto 0) := "0111";
    constant OP_CMP : std_logic_vector(3 downto 0) := "1000";
    constant OP_MUL : std_logic_vector(3 downto 0) := "1001";

    signal res_i   : std_logic_vector(WIDTH-1 downto 0);
    signal add_ext : std_logic_vector(WIDTH downto 0);
    signal sub_ext : std_logic_vector(WIDTH downto 0);

begin

    add_ext <= std_logic_vector(unsigned('0' & a) + unsigned('0' & b));
    sub_ext <= std_logic_vector(unsigned('0' & a) - unsigned('0' & b));

    process(a, b, op, add_ext, sub_ext)
        variable mul_full : std_logic_vector(2*WIDTH-1 downto 0);
    begin
        carry <= '0';
        ovf   <= '0';

        case op is
            when OP_ADD =>
                res_i <= add_ext(WIDTH-1 downto 0);
                carry <= add_ext(WIDTH);
                ovf   <= (not a(WIDTH-1) and not b(WIDTH-1) and add_ext(WIDTH-1))
                      or (a(WIDTH-1) and b(WIDTH-1) and not add_ext(WIDTH-1));

            when OP_SUB =>
                res_i <= sub_ext(WIDTH-1 downto 0);
                carry <= sub_ext(WIDTH);
                ovf   <= (not a(WIDTH-1) and b(WIDTH-1) and add_ext(WIDTH-1))
                      or (a(WIDTH-1) and not b(WIDTH-1) and not add_ext(WIDTH-1));

            when OP_AND =>
                res_i <= a and b;

            when OP_OR =>
                res_i <= a or b;

            when OP_XOR =>
                res_i <= a xor b;

            when OP_SHL =>
                res_i <= std_logic_vector(
                    shift_left(unsigned(a), to_integer(unsigned(b(3 downto 0))))
                );

            when OP_SHR =>
                res_i <= std_logic_vector(
                    shift_right(unsigned(a), to_integer(unsigned(b(3 downto 0))))
                );

            when OP_NOT =>
                res_i <= not a;

            when OP_CMP =>
                if unsigned(a) < unsigned(b) then
                    res_i <= (others => '1');
                else
                    res_i <= (others => '0');
                end if;

            when OP_MUL =>
                mul_full := std_logic_vector(unsigned(a) * unsigned(b));
                res_i <= mul_full(WIDTH-1 downto 0);
                carry <= mul_full(WIDTH);

            when others =>
                res_i <= (others => '0');
        end case;
    end process;

    result <= res_i;
    zero   <= '1' when unsigned(res_i) = 0 else '0';
    neg    <= res_i(WIDTH-1);

end architecture;
