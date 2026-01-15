#include <cstddef>
#include <cstdint>
#include <cstdio>

// Three simple target functions
// Use noinline to prevent optimization and ensure symbolization

void func_apple() {
    volatile int x = 1;
    (void)x;
}


void func_banana() {
    volatile int x = 2;
    (void)x;
}


void func_cherry() {
    volatile int x = 3;
    (void)x;
}

// Fuzzer entry point
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < 3) return 0;

    // Call functions based on first 3 bytes
    if (data[0] == 'A') func_apple();
    if (data[1] == 'B') func_banana();
    if (data[2] == 'C') func_cherry();

    // Success message when all hit
    if (data[0] == 'A' && data[1] == 'B' && data[2] == 'C') {
       // printf("✓ Found ABC! All 3 functions hit!\n");
    }

    return 0;
}
