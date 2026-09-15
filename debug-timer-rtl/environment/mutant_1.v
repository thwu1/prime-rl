`timescale 1ns / 1ps
// Mutant 1: prescaler comparison uses > instead of >= (off-by-one tick rate)
module timer_apb (
    input  wire        pclk,
    input  wire        presetn,
    input  wire [7:0]  paddr,
    input  wire        psel,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [31:0] pwdata,
    output reg  [31:0] prdata,
    output wire        pready,
    output wire        irq,
    input  wire        capture_in_0,
    input  wire        capture_in_1
);

    assign pready = 1'b1;

    reg [31:0] global_ctrl;
    reg [31:0] int_en;
    reg [31:0] int_flag;
    reg [31:0] ch0_ctrl, ch0_cnt, ch0_cmp, ch0_cap;
    reg [31:0] ch1_ctrl, ch1_cnt, ch1_cmp, ch1_cap;

    wire        global_en     = global_ctrl[0];
    wire [7:0]  prescaler_div = global_ctrl[15:8];
    wire        apb_wr        = psel && penable && pwrite;

    reg  [7:0] prescaler_cnt;
    reg        tick;

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            prescaler_cnt <= 8'd0;
            tick          <= 1'b0;
        end else if (!global_en) begin
            prescaler_cnt <= 8'd0;
            tick          <= 1'b0;
        end else begin
            if (prescaler_cnt > prescaler_div) begin  // BUG: > instead of >=
                prescaler_cnt <= 8'd0;
                tick          <= 1'b1;
            end else begin
                prescaler_cnt <= prescaler_cnt + 8'd1;
                tick          <= 1'b0;
            end
        end
    end

    reg [1:0] cap0_sync, cap1_sync;

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            cap0_sync <= 2'b00;
            cap1_sync <= 2'b00;
        end else begin
            cap0_sync <= {cap0_sync[0], capture_in_0};
            cap1_sync <= {cap1_sync[0], capture_in_1};
        end
    end

    wire cap0_rise = ~cap0_sync[1] &  cap0_sync[0];
    wire cap0_fall =  cap0_sync[1] & ~cap0_sync[0];
    wire cap1_rise = ~cap1_sync[1] &  cap1_sync[0];
    wire cap1_fall =  cap1_sync[1] & ~cap1_sync[0];

    wire cap0_evt = ch0_ctrl[3] ? cap0_fall : cap0_rise;
    wire cap1_evt = ch1_ctrl[3] ? cap1_fall : cap1_rise;

    reg ch0_match_evt, ch0_ovf_evt;

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            ch0_cnt       <= 32'd0;
            ch0_match_evt <= 1'b0;
            ch0_ovf_evt   <= 1'b0;
        end else begin
            ch0_match_evt <= 1'b0;
            ch0_ovf_evt   <= 1'b0;
            if (apb_wr && paddr == 8'h14) begin
                ch0_cnt <= pwdata;
            end else if (ch0_ctrl[0] && tick) begin
                if (ch0_cmp != 32'd0 && ch0_cnt == ch0_cmp) begin
                    ch0_match_evt <= 1'b1;
                    ch0_cnt <= ch0_ctrl[1] ? 32'd0 : ch0_cnt;
                end else if (ch0_cnt == 32'hFFFFFFFF) begin
                    ch0_ovf_evt <= 1'b1;
                    ch0_cnt     <= 32'd0;
                end else begin
                    ch0_cnt <= ch0_cnt + 32'd1;
                end
            end
        end
    end

    always @(posedge pclk or negedge presetn) begin
        if (!presetn)
            ch0_cap <= 32'd0;
        else if (ch0_ctrl[2] && cap0_evt)
            ch0_cap <= ch0_cnt;
    end

    reg ch1_match_evt, ch1_ovf_evt;

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            ch1_cnt       <= 32'd0;
            ch1_match_evt <= 1'b0;
            ch1_ovf_evt   <= 1'b0;
        end else begin
            ch1_match_evt <= 1'b0;
            ch1_ovf_evt   <= 1'b0;
            if (apb_wr && paddr == 8'h24) begin
                ch1_cnt <= pwdata;
            end else if (ch1_ctrl[0] && tick) begin
                if (ch1_cmp != 32'd0 && ch1_cnt == ch1_cmp) begin
                    ch1_match_evt <= 1'b1;
                    ch1_cnt <= ch1_ctrl[1] ? 32'd0 : ch1_cnt;
                end else if (ch1_cnt == 32'hFFFFFFFF) begin
                    ch1_ovf_evt <= 1'b1;
                    ch1_cnt     <= 32'd0;
                end else begin
                    ch1_cnt <= ch1_cnt + 32'd1;
                end
            end
        end
    end

    always @(posedge pclk or negedge presetn) begin
        if (!presetn)
            ch1_cap <= 32'd0;
        else if (ch1_ctrl[2] && cap1_evt)
            ch1_cap <= ch1_cnt;
    end

    wire [3:0] new_events = {ch1_ovf_evt, ch1_match_evt,
                             ch0_ovf_evt, ch0_match_evt};

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            int_flag <= 32'd0;
        end else begin
            if (apb_wr && paddr == 8'h08)
                int_flag[3:0] <= (int_flag[3:0] | new_events) & ~pwdata[3:0];
            else
                int_flag[3:0] <= int_flag[3:0] | new_events;
        end
    end

    assign irq = |(int_flag[3:0] & int_en[3:0]);

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            global_ctrl <= 32'd0;
            int_en      <= 32'd0;
            ch0_ctrl    <= 32'd0;
            ch0_cmp     <= 32'd0;
            ch1_ctrl    <= 32'd0;
            ch1_cmp     <= 32'd0;
        end else if (apb_wr) begin
            case (paddr)
                8'h00: global_ctrl <= pwdata;
                8'h04: int_en      <= pwdata;
                8'h10: ch0_ctrl    <= pwdata;
                8'h18: ch0_cmp     <= pwdata;
                8'h20: ch1_ctrl    <= pwdata;
                8'h28: ch1_cmp     <= pwdata;
                default: ;
            endcase
        end
    end

    always @(*) begin
        prdata = 32'd0;
        if (psel && !pwrite) begin
            case (paddr)
                8'h00: prdata = global_ctrl;
                8'h04: prdata = int_en;
                8'h08: prdata = int_flag;
                8'h10: prdata = ch0_ctrl;
                8'h14: prdata = ch0_cnt;
                8'h18: prdata = ch0_cmp;
                8'h1C: prdata = ch0_cap;
                8'h20: prdata = ch1_ctrl;
                8'h24: prdata = ch1_cnt;
                8'h28: prdata = ch1_cmp;
                8'h2C: prdata = ch1_cap;
                default: prdata = 32'd0;
            endcase
        end
    end

endmodule
