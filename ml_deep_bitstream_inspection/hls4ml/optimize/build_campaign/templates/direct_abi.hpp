#ifndef DIRECT_ABI_HPP
#define DIRECT_ABI_HPP
#include <cstdint>
namespace direct {
constexpr uint64_t signature=0x4342595400030000ULL;
enum Register:unsigned {STATUS=0,RAW_BYTES=1,TRIAL=2,SIGNATURE=4,TICK=5,ORIGIN=6,EVENTS=7,
    RAW_FIRST=8,RAW_LAST=9,PP_FIRST=10,PP_LAST=11,CNN_FIRST=12,CNN_LAST=13,
    LOGIT=14,VERDICT_TICK=15,READ_ACK=16,WRITE_ACK=17,TX_FIRST=18,TX_LAST=19,
    INPUT_BEATS=20,OUTPUT_BEATS=21,INPUT_STARVE=22,INPUT_BLOCKED=23,PP_BLOCKED=24,
    CNN_STARVE=25,RESULT=26,PP_COUNT=27,CNN_COUNT=28,FIFO_MAX=29};
struct alignas(64) GpuResult {uint32_t logit_bits;uint32_t magic;uint64_t trial;uint64_t reserved[6];};
static_assert(sizeof(GpuResult)==64,"GPU result must be one AXI beat");
constexpr uint32_t result_magic=0x43565233;
}
#endif
