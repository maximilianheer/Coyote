// Read-only MMIO-width diagnostic for the existing direct-checker ABI v3.
// Hold board_device.lock externally; no register writes, DMA, or programming.
#include <cstdint>
#include <cstdio>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const int fd = open(argv[1], O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open"); return 2; }
    void* mapping = mmap(nullptr, 65536, PROT_READ, MAP_SHARED, fd, 3 * 4096);
    if (mapping == MAP_FAILED) { perror("mmap"); close(fd); return 2; }
    auto q = static_cast<volatile uint64_t*>(mapping);
    auto d = static_cast<volatile uint32_t*>(mapping);
    int failures = 0;
    if (q[4] != UINT64_C(0x4342595400030007) || (q[0] & 1)) {
        fprintf(stderr, "Expected idle D_I ABI v3; no writes performed\n");
        failures = 1;
    } else {
        puts("repeat,register,before64,split32,after64,equal");
        // Exclude the free-running tick register (5).
        for (unsigned repeat = 0; repeat < 100; ++repeat) {
            for (unsigned reg = 0; reg < 30; ++reg) {
                if (reg == 5) continue;
                const uint64_t before = q[reg];
                const uint32_t low = d[2 * reg];
                const uint32_t high = d[2 * reg + 1];
                const uint64_t split = uint64_t(low) | (uint64_t(high) << 32);
                const uint64_t after = q[reg];
                const bool equal = before == split && split == after;
                failures += !equal;
                printf("%u,%u,%016llx,%016llx,%016llx,%u\n", repeat, reg,
                       (unsigned long long)before, (unsigned long long)split,
                       (unsigned long long)after, unsigned(equal));
            }
        }
    }
    munmap(mapping, 65536);
    close(fd);
    return failures ? 1 : 0;
}
