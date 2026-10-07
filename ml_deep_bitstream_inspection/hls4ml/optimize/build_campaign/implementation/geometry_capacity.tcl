open_checkpoint [lindex $argv 0]
foreach cr [lsort [get_clock_regions]] {
    set ram [get_sites -quiet -of_objects $cr -filter {NAME =~ RAMB18*}]
    puts "CAPACITY $cr RAMB18 [llength $ram]"
}
exit 0
