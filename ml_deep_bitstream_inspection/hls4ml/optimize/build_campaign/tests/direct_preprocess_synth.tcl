set root $::env(DIRECT_JOB)
set src "$root/hw/src/hls/preprocess_wrapper"
open_project -reset "$root/preprocess_validation_hls"
set_top preprocess_wrapper
add_files "$src/preprocess_wrapper.cpp" -cflags "-std=c++14 -I$src"
open_solution -reset solution1 -flow_target vivado
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 4 -name default
set_clock_uncertainty 27%
csynth_design
exit
