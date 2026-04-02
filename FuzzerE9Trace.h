// Shared interface between the e9patch hook and libFuzzer.
// Plain C — no C++ types, no includes beyond stdint/stddef.
// The hook writes into this buffer during execution.
// libFuzzer reads it after execution to populate CurrentExecutionPath.

#ifndef FUZZER_E9_TRACE_H
#define FUZZER_E9_TRACE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define E9_TRACE_MAX_EVENTS 4096
#define E9_TRACE_MAX_SYMBOLS 512
#define E9_TRACE_MAX_NAME_LEN 128

// One recorded call event.
struct E9TraceEvent {
    uintptr_t target;   // runtime address of call target
    uint32_t  seq;      // global sequence number
    uint32_t  call_id;  // per-target call count
};

// Symbol lookup entry: maps a runtime address to a function name.
struct E9TraceSymbol {
    uintptr_t addr;
    char      name[E9_TRACE_MAX_NAME_LEN];
};

// The shared trace buffer. One global instance, accessed by both the
// e9patch hook (writer) and libFuzzer (reader).
struct E9TraceBuffer {
    // Written by hook
    struct E9TraceEvent events[E9_TRACE_MAX_EVENTS];
    uint32_t num_events;
    uint32_t overflow;    // set to 1 if events exceeded max
    uint32_t active;      // hook only records when active==1

    // Written by libFuzzer at init (symbol table for address resolution)
    struct E9TraceSymbol symbols[E9_TRACE_MAX_SYMBOLS];
    uint32_t num_symbols;
    uintptr_t base_addr;  // runtime base address for PIE offset computation
};

// Global buffer — defined in FuzzerE9Trace.cpp, accessed by hook via dlsym
// or direct linking.
extern struct E9TraceBuffer e9_trace_buf;

// Called by libFuzzer before each execution.
void e9_trace_reset(void);

// Called by the e9patch hook on each call instruction.
void e9_trace_record(uintptr_t target);

// Called by libFuzzer to add a symbol mapping.
void e9_trace_add_symbol(uintptr_t addr, const char *name);

// Called by libFuzzer to set the PIE base address.
void e9_trace_set_base(uintptr_t base);

#ifdef __cplusplus
}
#endif

#endif // FUZZER_E9_TRACE_H
