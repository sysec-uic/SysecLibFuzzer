/* e9patch hook for libFuzzer integration.
 * Writes call events into e9_trace_buf. Buffer address passed as arg.
 * Only records calls to focus functions (matched by static offset).
 * call_id is computed on the libFuzzer side.
 */
#include "stdlib.c"

#define E9_TRACE_MAX_EVENTS  4096
#define E9_TRACE_MAX_SYMBOLS 512
#define E9_TRACE_MAX_NAME_LEN 128

struct E9TraceEvent {
    uintptr_t target;
    uint32_t  seq;
    uint32_t  call_id;
};

struct E9TraceSymbol {
    uintptr_t addr;
    char      name[E9_TRACE_MAX_NAME_LEN];
};

struct E9TraceBuffer {
    struct E9TraceEvent events[E9_TRACE_MAX_EVENTS];
    uint32_t num_events;
    uint32_t overflow;
    uint32_t active;
    struct E9TraceSymbol symbols[E9_TRACE_MAX_SYMBOLS];
    uint32_t num_symbols;
    uintptr_t base_addr;
};

void entry(const void *target, void *buf_ptr) {
    struct E9TraceBuffer *buf = (struct E9TraceBuffer *)buf_ptr;
    if (!buf || !buf->active) return;

    /* Check if this target is a focus function. */
    uintptr_t t = (uintptr_t)target;
    uint32_t nsyms = buf->num_symbols;
    int found = 0;
    for (uint32_t i = 0; i < nsyms; i++) {
        if (buf->symbols[i].addr == t) {
            found = 1;
            break;
        }
    }
    if (!found) return;

    uint32_t idx = buf->num_events;
    if (idx >= E9_TRACE_MAX_EVENTS) {
        buf->overflow = 1;
        return;
    }

    buf->events[idx].target  = t;
    buf->events[idx].seq     = idx + 1;
    buf->events[idx].call_id = 0;
    buf->num_events = idx + 1;
}

void init(int argc, char **argv, char **envp) {
    environ = envp;
}
