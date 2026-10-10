set root $::env(FRAME_START_CHECK)
set top $::env(FRAME_START_TOP)
open_project -reset "$root/hls"
set_top $top
add_files "$root/kernel/$top.cpp" -cflags "-std=c++14 -I$root/kernel"
add_files "$root/kernel/firmware/prod_res256_manualA_coyote_accel.cpp" -cflags "-std=c++14 -I$root/kernel"
open_solution -reset solution1 -flow_target vivado
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 4 -name default
set_clock_uncertainty 27%
csynth_design
exit
