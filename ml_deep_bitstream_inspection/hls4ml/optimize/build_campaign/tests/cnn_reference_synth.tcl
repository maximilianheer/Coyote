set root $::env(DIRECT_JOB)
open_project -reset "$root/reference_hls"
set_top cnn_wrapper
add_files "$root/reference/cnn_wrapper.cpp" -cflags "-std=c++14 -I$root/reference"
add_files "$root/reference/firmware/prod_res256_manualA_coyote_accel.cpp" -cflags "-std=c++14 -I$root/reference"
open_solution -reset solution1 -flow_target vivado
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 4 -name default
set_clock_uncertainty 27%
csynth_design
exit
