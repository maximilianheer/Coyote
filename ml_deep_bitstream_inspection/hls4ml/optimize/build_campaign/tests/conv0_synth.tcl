# Run from an isolated validation snapshot; no repository writes.
set top $::env(CONV0_TOP)
open_project -reset $top
set_top $top
add_files conv0_check.cpp -cflags {-std=c++14 -I.}
open_solution -reset solution1 -flow_target vivado
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 4 -name default
set_clock_uncertainty 27%
csynth_design
exit
