# Path-Aware Fuzzing via e9patch Binary Rewriting

## Overview

This document describes how to use e9patch binary rewriting to capture runtime
function call traces and use them to direct fuzzing toward a known crash path.

The technique works on pre-compiled binaries. It does not require the target's
source code to be modified or recompiled with special instrumentation flags
(beyond the standard `-fsanitize=fuzzer-no-link` for libFuzzer coverage).

## The Problem

When a crash is found (e.g., via OSS-Fuzz or ARVO), we get a stack trace showing
which functions were involved. But the stack trace is a single snapshot — it
doesn't tell us the full execution sequence: which functions were called first,
how many times each was called, or the order of calls leading up to the crash.

Without this information, the fuzzer has no way to steer toward inputs that
follow the crash's execution pattern. It relies on coverage alone, which cannot
distinguish "parsed one XML element" from "parsed 200 nested elements" — even
though the crash only occurs in the deeply nested case.

## The Approach

1. Extract the relevant function names from the crash stack trace
2. Run a crash-triggering input (PoC) through an instrumented binary to record
   the full ordered call sequence
3. Use that recorded sequence as a reference to guide fuzzing — inputs whose
   execution follows a similar path are kept, others are discarded

## Prerequisites

- Docker
- The SysecLibFuzzer repository with the `add-binary-rewriting-log-feature` branch

## Step-by-Step

### Step 1: Get the crash data from ARVO

Each entry in the ARVO database has:
- `crash_output` — the full ASan/sanitizer stack trace
- `reproducer_vul` — a Docker command to access the PoC input

Extract the focus functions from the stack trace:

```bash
# Save the crash output to a file
python3 -c "
import sqlite3
db = sqlite3.connect('custom_scripts/arvo.db.2.enriched')
cur = db.cursor()
cur.execute('SELECT crash_output FROM arvo WHERE localId = 42470339')
open('/tmp/crash_log.txt', 'w').write(cur.fetchone()[0])
"

# Extract focus function names (filters out libFuzzer, ASan, libc internals)
python3 custom_scripts/focus_functions_list.py /tmp/crash_log.txt
```

Output:
```
focus_functions="xmlSAX2AttributeNs", "xmlSAX2StartElementNs", "xmlParseStartTag2", "xmlParseElement", "xmlParseContent"
focus_functions_count=5
```

### Step 2: Get the PoC input

Pull the PoC from the ARVO Docker image:

```bash
docker pull n132/arvo:42470339-vul
docker run --rm n132/arvo:42470339-vul cat /tmp/poc > /tmp/poc.bin
```

### Step 3: Build the instrumented binary

The Docker image builds everything:

```bash
docker build -t sysec-libfuzzer-e9 -f docker-e9/Dockerfile .
```

This produces two binaries inside the container:
- `/out/xml_fuzz` — the unpatched fuzzer (for normal fuzzing)
- `/out/xml_fuzz_patched` — the e9patch-instrumented fuzzer (records call traces)

The build process:
1. Compiles libxml2 with `-O1 -fno-inline -fno-optimize-sibling-calls` so
   function calls remain as `call` instructions (not inlined or tail-call optimized)
2. Links against `libFuzzer.a` which includes `FuzzerE9Trace.cpp` (the shared trace buffer)
3. Runs `e9tool` to patch every `call` instruction in the binary with a trampoline
   that records the call target into the shared buffer

### Step 4: Record the crash execution path

Run the PoC through the patched binary to capture what the crash execution
looks like at the function call level:

```bash
mkdir -p /tmp/crash_path /tmp/corpus
cp /tmp/poc.bin /tmp/corpus/poc.bin

docker run --rm \
    -v /tmp/crash_path:/out/traces \
    -v /tmp/corpus:/out/corpus \
    sysec-libfuzzer-e9 \
    /out/xml_fuzz_patched /out/corpus \
    -focus_functions=xmlSAX2StartElementNs,xmlParseElement,xmlParseContent,xmlReadMemory \
    -trace_output_dir=/out/traces \
    -trace_only_on_corpus=0 \
    -runs=1
```

This produces a JSON trace file in `/tmp/crash_path/`:

```json
{
  "input_hash": "a38de292c875beab",
  "input_size": 846,
  "input_hex": "3c21444f435459...",
  "input_ascii": "<!DOCTYPE  A[<!ENTITY...",
  "path": [
    {"func": "xmlReadMemory",        "call_id": 1, "bb": 1829440},
    {"func": "xmlParseElement",      "call_id": 1, "bb": 1782288},
    {"func": "xmlSAX2StartElementNs","call_id": 1, "bb": 2716128},
    {"func": "xmlParseContent",      "call_id": 1, "bb": 1782800},
    {"func": "xmlSAX2StartElementNs","call_id": 2, "bb": 2716128},
    {"func": "xmlSAX2StartElementNs","call_id": 3, "bb": 2716128},
    ...
    {"func": "xmlSAX2StartElementNs","call_id": 516, "bb": 2716128}
  ]
}
```

The `path` array is the ordered sequence of focus function calls during the
crash execution. In this case, the PoC triggers 516 calls to
`xmlSAX2StartElementNs` because of deeply nested XML elements.

### Step 5: Fuzz toward the crash path

Use the recorded path as a reference. The fuzzer compares each new input's
execution path against this reference and rejects inputs that are too different:

```bash
mkdir -p /tmp/traces
cp /tmp/crash_path/*.json /tmp/crash_ref.json

docker run --rm \
    -v /tmp/traces:/out/traces \
    -v /tmp/corpus:/out/corpus \
    -v /tmp/crash_ref.json:/out/crash.json:ro \
    sysec-libfuzzer-e9 \
    /out/xml_fuzz_patched /out/corpus \
    -focus_functions=xmlSAX2StartElementNs,xmlParseElement,xmlParseContent,xmlReadMemory \
    -trace_output_dir=/out/traces \
    -trace_only_on_corpus=0 \
    -crash_path_file=/out/crash.json \
    -path_distance_threshold=50 \
    -runs=1000
```

The key flags:
- `-crash_path_file` — the JSON trace from Step 4
- `-path_distance_threshold=50` — reject inputs whose path differs by more than
  50 steps from the crash path

The fuzzer will keep inputs that produce execution paths similar to the crash
(e.g., inputs that trigger many calls to `xmlSAX2StartElementNs` through deep
nesting) and discard inputs that don't reach the relevant code.

### Step 6: Inspect the traces

Each execution that passes the distance filter produces a JSON trace:

```bash
# Count traces
ls /tmp/traces/*.json | wc -l

# Summarize a trace
python3 -c "
import json
data = json.load(open('/tmp/traces/<hash>.json'))
print(f'Input: {data[\"input_ascii\"][:60]}')
print(f'Size:  {data[\"input_size\"]} bytes')
print(f'Path:  {len(data[\"path\"])} calls')
from collections import Counter
for func, cnt in Counter(e['func'] for e in data['path']).most_common():
    print(f'  {func}: {cnt}')
"
```

## One-Command Demo

To run the full pipeline (Steps 1-6) automatically:

```bash
./docker-e9/run_full_pipeline.sh
```

This pulls the ARVO PoC, records the crash path, and fuzzes toward it.
Results are in `/tmp/e9_pipeline/`.

## How It Works Internally

### The e9patch hook

e9patch is a static binary rewriter. It patches `call` instructions in the
binary to jump through trampolines that execute our hook code before continuing
to the original call target.

The hook (`e9patch_experiments/hook_integrated.c`):
1. Receives the call target address and a pointer to the shared trace buffer
2. Checks if the target is a focus function (by comparing against the symbol
   table stored in the buffer)
3. If yes, records it; if no, skips it

### The shared trace buffer

`FuzzerE9Trace.h` defines a shared struct between the hook and libFuzzer:

```
┌─────────────────────────────────┐
│ events[4096]                    │  ← hook writes here
│   .target  (call target addr)   │
│   .seq     (sequence number)    │
│   .call_id (unused by hook)     │
│ num_events                      │
│ overflow                        │
│ active                          │  ← libFuzzer toggles this
├─────────────────────────────────┤
│ symbols[512]                    │  ← libFuzzer writes here at init
│   .addr    (static offset)      │
│   .name    (function name)      │
│ num_symbols                     │
│ base_addr                       │
└─────────────────────────────────┘
```

### The fuzzer integration

In `FuzzerLoop.cpp`, for each execution:
1. `e9_trace_reset()` — zeros the buffer, sets `active=1`
2. `ExecuteCallback()` — runs the target; the hook fires on every `call`
3. `CollectE9Trace()` — reads the buffer, resolves addresses to names,
   populates `CurrentExecutionPath`
4. `ComputePathDistance()` — compares against the crash path
5. `DumpCurrentPath()` — writes JSON trace if within distance threshold

### Function name resolution

The hook records static (file) offsets, not runtime addresses. At startup,
`InitE9SymbolTable()` computes each focus function's static offset by:
1. Finding the function's coverage counter in the PC table
2. Getting the runtime address via `dladdr`
3. Subtracting the PIE base address to get the file offset
4. Storing it in the symbol table

The hook compares call targets directly against these offsets.

## Build Flags

The target binary requires specific flags:

| Flag | Why |
|------|-----|
| `-fno-inline` | Prevents inlining so functions remain as `call` instructions |
| `-fno-optimize-sibling-calls` | Prevents tail-call optimization (`jmp` instead of `call`) |
| `-rdynamic` | Exports symbols to the dynamic table so `dladdr` can resolve names |
| `-ldl` | Links the dl library for `dladdr` |

## Limitations

- **Only tested on libxml2.** Other targets may have different issues.
- **Path-aware fuzzing not validated.** The traces are generated and fed into
  `ComputePathDistance()`, but the effect on fuzzing outcomes has not been
  measured.
- **ASan incompatible with e9patch.** Crash detection and trace recording
  cannot happen in the same binary. Use the unpatched binary with ASan to
  find crashes, and the patched binary without ASan to record traces.
- **`F.name` matching in e9tool does not work.** The workaround is
  `asm=/call.*/` which patches all call instructions; filtering happens
  inside the hook.
- **Performance not measured.** The hook fires on every `call` instruction
  (even if it skips non-focus calls quickly). Impact on fuzzing throughput
  is unknown.

## Files

| File | Purpose |
|------|---------|
| `FuzzerE9Trace.h` | Shared buffer struct definition |
| `FuzzerE9Trace.cpp` | Buffer implementation |
| `FuzzerTracePC.cpp` | `CollectE9Trace()`, `InitE9SymbolTable()`, `GetFunctionName()` |
| `FuzzerLoop.cpp` | Integration points (reset, collect, init) |
| `e9patch_experiments/hook_integrated.c` | The e9patch hook |
| `e9patch_experiments/hook.c` | Standalone hook (stderr, for debugging) |
| `e9patch_experiments/setup.sh` | Installs e9patch |
| `e9patch_experiments/run_integrated.sh` | Toy target demo |
| `docker-e9/Dockerfile` | Builds libxml2 + libFuzzer + e9patch |
| `docker-e9/run_full_pipeline.sh` | End-to-end: PoC → crash path → directed fuzzing |
| `custom_scripts/focus_functions_list.py` | Extracts focus functions from crash log (pre-existing) |
