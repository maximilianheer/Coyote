#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <immintrin.h>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>

static std::uint64_t sample(const volatile std::uint8_t* input, std::size_t size) {
    std::uint64_t sum = 0;
    for (std::uint64_t index = 0; index < 65536; ++index) {
        sum += input[index * (size - 1) / 65535];
    }
    return sum;
}

int main() {
    const std::size_t size = 134217664;
    void* allocation = nullptr;
    if (posix_memalign(&allocation, 2097152, 134217728)) return 1;
    auto* input = reinterpret_cast<std::uint8_t*>(allocation);
    std::memset(input, 1, 134217728);
    int leader = -1;
    const std::uint64_t events[] = {PERF_COUNT_HW_CPU_CYCLES, PERF_COUNT_HW_INSTRUCTIONS,
                                   PERF_COUNT_HW_CACHE_REFERENCES, PERF_COUNT_HW_CACHE_MISSES};
    for (const auto event : events) {
        perf_event_attr attribute = {};
        attribute.size = sizeof(attribute);
        attribute.type = PERF_TYPE_HARDWARE;
        attribute.config = event;
        attribute.disabled = 1;
        attribute.exclude_kernel = 1;
        attribute.exclude_hv = 1;
        attribute.read_format = PERF_FORMAT_GROUP;
        int fd = syscall(__NR_perf_event_open, &attribute, 0, -1, leader, 0);
        if (fd < 0) { std::cerr << "perf_event_open failed\n"; return 2; }
        if (leader < 0) leader = fd;
    }
    std::cout << "[\n";
    bool first = true;
    for (unsigned trial = 0; trial < 40; ++trial) {
        const bool cold = trial % 2 == 0;
        if (cold) {
            for (std::size_t offset = 0; offset < size; offset += 64) _mm_clflushopt(input + offset);
            _mm_sfence();
            _mm_mfence();
        } else {
            volatile auto warm = sample(input, size);
            (void)warm;
        }
        ioctl(leader, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
        ioctl(leader, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
        volatile auto sum = sample(input, size);
        ioctl(leader, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
        if (sum != 65536) return 3;
        std::uint64_t values[5] = {};
        if (read(leader, values, sizeof(values)) != sizeof(values) || values[0] != 4) return 4;
        if (!first) std::cout << ",\n";
        first = false;
        std::cout << "{\"trial\":" << trial << ",\"cold\":" << (cold ? "true" : "false")
                  << ",\"cycles\":" << values[1] << ",\"instructions\":" << values[2]
                  << ",\"cache_references\":" << values[3] << ",\"cache_misses\":" << values[4] << "}";
    }
    std::cout << "\n]\n";
    return 0;
}
