// Priority encoder - selects lowest-index asserted bit
module priority_enc
#(
  parameter int WIDTH = 4
)(
  input  logic [WIDTH-1:0]           req,
  output logic [$clog2(WIDTH)-1:0]   idx,
  output logic                       valid
);

  assign valid = |req;

  always_comb begin
    idx = '0;
    for (int i = WIDTH - 1; i >= 0; i--) begin
      if (req[i])
        idx = i[$clog2(WIDTH)-1:0];
    end
  end

endmodule
