# Run on a fresh, isolated HLS IP export before the Coyote project imports it.
# HDL additions live in ordinary maintained files, never Python source strings.
# Existing HLS logic, FIFO, reset, start, and ready assignments remain unchanged.
namespace eval passive_taps {
    proc read_file {path} {
        set f [open $path r]; set data [read $f]; close $f; return $data
    }
    proc write_file {path data} {
        set f [open $path w]; puts -nonewline $f $data; close $f
    }
    proc insert_once {text marker addition before} {
        set start [string first $marker $text]
        if {$start<0 || [string first $marker $text [expr {$start+1}]]>=0} {
            error "Passive tap anchor absent or ambiguous: $marker"
        }
        set position [expr {$before ? $start : $start+[string length $marker]}]
        return "[string range $text 0 [expr {$position-1}]]$addition[string range $text $position end]"
    }
    proc verilog {path snippets} {
        set original [read_file $path]
        if {[string first observer_pixel_ $original]>=0} {error "Already instrumented: $path"}
        if {![regexp {model_wrapper_fifo_w16_d32_S bitstream_input_U\(([^;]+)\);} $original _ fifo]} {
            error "Expected internal 16-bit, 32-token FIFO missing"
        }
        regsub -all {\s+} $fifo {} compact
        foreach required {
            .clk(ap_clk) .reset(ap_rst_n_inv) .if_read_ce(1'b1) .if_write_ce(1'b1)
            .if_full_n(bitstream_input_full_n) .if_empty_n(bitstream_input_empty_n)
            .if_write(raw_bitstream_downsample_to_input_stream_U0_bitstream_input_write)
            .if_read(production_infer_and_publish_U0_bitstream_input_read)
        } {
            if {[string first $required $compact]<0} {error "FIFO contract changed: $required"}
        }
        # The first ');' ends the non-ANSI top port list. All original bytes remain.
        set module_start [string first "module model_wrapper (" $original]
        set port_end [string first "\n);" $original $module_start]
        if {$module_start<0 || $port_end<0} {error "Unexpected model_wrapper declaration"}
        set ports [read_file "$snippets/fifo_tap_ports.vh"]
        set result "[string range $original 0 [expr {$port_end-1}]]$ports[string range $original $port_end end]"
        set result [insert_once $result "endmodule //model_wrapper" [read_file "$snippets/fifo_taps.vh"] 1]
        write_file $path $result
    }
    proc vhdl {path snippets} {
        set original [read_file $path]
        if {[string first observer_pixel_ $original]>=0} {error "Already instrumented: $path"}
        if {![regexp {bitstream_input_U : component model_wrapper_fifo_w16_d32_S\s+port map\s*\(([^;]+)\);} $original _ fifo]} {
            error "Expected VHDL internal 32-token FIFO missing"
        }
        regsub -all {\s+} $fifo {} compact
        foreach required {
            clk=>ap_clk reset=>ap_rst_n_inv if_read_ce=>ap_const_logic_1
            if_write_ce=>ap_const_logic_1 if_full_n=>bitstream_input_full_n
            if_empty_n=>bitstream_input_empty_n
            if_write=>raw_bitstream_downsample_to_input_stream_U0_bitstream_input_write
            if_read=>production_infer_and_publish_U0_bitstream_input_read
        } {
            if {[string first $required $compact]<0} {error "VHDL FIFO contract changed: $required"}
        }
        set result [insert_once $original "entity model_wrapper is\nport (\n" [read_file "$snippets/fifo_tap_ports.vhd.inc"] 0]
        set result [insert_once $result "end behav;" [read_file "$snippets/fifo_taps.vhd.inc"] 1]
        write_file $path $result
    }
    proc package {ipdir snippets} {
        verilog "$ipdir/hdl/verilog/model_wrapper.v" $snippets
        vhdl "$ipdir/hdl/vhdl/model_wrapper.vhd" $snippets
        set core [ipx::open_core "$ipdir/component.xml"]
        foreach name {observer_pixel_write observer_pixel_read} {
            if {[llength [ipx::get_ports $name -of_objects $core]]} {error "Tap port already packaged"}
            set port [ipx::add_port $name $core]
            set_property direction out $port
            set_property type_name std_logic $port
        }
        ipx::update_checksums $core
        ipx::check_integrity $core
        ipx::save_core $core
        ipx::unload_core $core
        puts "PASS passive FIFO tap export: $ipdir"
    }
}
