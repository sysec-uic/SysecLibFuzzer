// Implementation of the shared e9patch trace buffer.
// Compiled into libFuzzer.a so it lives in the same process as the hook.

#include "FuzzerE9Trace.h"
#include <string.h>

// The global buffer — both the hook and libFuzzer access this.
struct E9TraceBuffer e9_trace_buf;

// Per-target call counting (internal to e9_trace_record).
static struct {
    uintptr_t addr;
    uint32_t  count;
    int       used;
} e9_call_counts[E9_TRACE_MAX_SYMBOLS];

void e9_trace_reset(void) {
    e9_trace_buf.num_events = 0;
    e9_trace_buf.overflow = 0;
    e9_trace_buf.active = 1;  // Start recording
    memset(e9_call_counts, 0, sizeof(e9_call_counts));
}

static uint32_t e9_hash(uintptr_t a) {
    a ^= a >> 16;
    a *= 0x45d9f3b;
    a ^= a >> 16;
    return (uint32_t)(a & (E9_TRACE_MAX_SYMBOLS - 1));
}

static uint32_t e9_get_and_inc(uintptr_t addr) {
    uint32_t idx = e9_hash(addr);
    for (uint32_t i = 0; i < E9_TRACE_MAX_SYMBOLS; i++) {
        uint32_t slot = (idx + i) & (E9_TRACE_MAX_SYMBOLS - 1);
        if (e9_call_counts[slot].used && e9_call_counts[slot].addr == addr)
            return ++e9_call_counts[slot].count;
        if (!e9_call_counts[slot].used) {
            e9_call_counts[slot].addr = addr;
            e9_call_counts[slot].count = 1;
            e9_call_counts[slot].used = 1;
            return 1;
        }
    }
    return 0;
}

void e9_trace_record(uintptr_t target) {
    uint32_t idx = e9_trace_buf.num_events;
    if (idx >= E9_TRACE_MAX_EVENTS) {
        e9_trace_buf.overflow = 1;
        return;
    }
    uint32_t call_id = e9_get_and_inc(target);
    e9_trace_buf.events[idx].target = target;
    e9_trace_buf.events[idx].seq = idx + 1;
    e9_trace_buf.events[idx].call_id = call_id;
    e9_trace_buf.num_events = idx + 1;
}

void e9_trace_add_symbol(uintptr_t addr, const char *name) {
    uint32_t idx = e9_trace_buf.num_symbols;
    if (idx >= E9_TRACE_MAX_SYMBOLS) return;
    e9_trace_buf.symbols[idx].addr = addr;
    strncpy(e9_trace_buf.symbols[idx].name, name, E9_TRACE_MAX_NAME_LEN - 1);
    e9_trace_buf.symbols[idx].name[E9_TRACE_MAX_NAME_LEN - 1] = '\0';
    e9_trace_buf.num_symbols = idx + 1;
}

void e9_trace_set_base(uintptr_t base) {
    e9_trace_buf.base_addr = base;
}
