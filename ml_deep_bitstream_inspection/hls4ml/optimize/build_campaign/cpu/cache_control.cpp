#include <immintrin.h>
#include <sys/mman.h>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

// This helper controls only the benchmark's own input pages. It performs no
// inference and does not change global caches, affinity or machine settings.
extern "C" {
void* allocate_arena(std::size_t bytes) {
    void* pointer = nullptr;
    if (posix_memalign(&pointer, 2 * 1024 * 1024, bytes) != 0) return nullptr;
    madvise(pointer, bytes, MADV_HUGEPAGE);
    return pointer;
}

void release_arena(void* pointer) { std::free(pointer); }

int collapse_arena(void* pointer, std::size_t bytes) {
    // Linux 6.1+: a failed best-effort collapse leaves a valid ordinary mapping.
    return madvise(pointer, bytes, 25);
}

void flush_input(void* pointer, std::size_t bytes) {
    auto first = reinterpret_cast<std::uintptr_t>(pointer) & ~std::uintptr_t(63);
    auto end = reinterpret_cast<std::uintptr_t>(pointer) + bytes;
    _mm_mfence();
    for (auto address = first; address < end; address += 64) {
        _mm_clflushopt(reinterpret_cast<void*>(address));
    }
    _mm_sfence();
    _mm_mfence();
}

std::uint64_t warm_selected(const std::uint8_t* pointer, std::size_t bytes) {
    const volatile std::uint8_t* input = pointer;
    std::uint64_t sum = 0;
    for (std::uint64_t sample = 0; sample < 65536; ++sample) {
        const auto position = bytes > 65536 ? sample * (bytes - 1) / 65535 : sample;
        if (position < bytes) sum += input[position];
    }
    return sum;
}

std::uint64_t warm_all(const std::uint8_t* pointer, std::size_t bytes) {
    const volatile std::uint8_t* input = pointer;
    std::uint64_t sum = 0;
    for (std::size_t offset = 0; offset < bytes; offset += 64) sum += input[offset];
    return sum;
}

std::uint64_t probe_line(const std::uint8_t* pointer, bool cold) {
    if (cold) {
        _mm_clflushopt(const_cast<std::uint8_t*>(pointer));
        _mm_sfence();
    } else {
        volatile std::uint8_t value = *pointer;
        (void)value;
    }
    _mm_mfence();
    _mm_lfence();
    const auto begin = __rdtsc();
    volatile std::uint8_t value = *pointer;
    (void)value;
    _mm_lfence();
    const auto end = __rdtsc();
    return end - begin;
}
}
