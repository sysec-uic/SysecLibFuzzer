# e9patch Experiments

Binary rewriting with [e9patch](https://github.com/GJDuck/e9patch) to get
runtime function call ordering — the piece that counter-based tracing in
`FuzzerTracePC.cpp` could not provide.

## Status

**Integrated and working.** The e9patch hook writes call traces to a shared
memory buffer. libFuzzer reads the buffer after each execution and populates
`CurrentExecutionPath` with real ordered function call data. This feeds
directly into `ComputePathDistance()` and `DumpCurrentPath()` (JSON trace
output). The counter-based path recording (which always produced `call_id=1`)
is automatically replaced when e9 trace data is present.

## Quick start

```bash
./setup.sh              # clone + build e9patch (one time)
./run_integrated.sh     # full demo: build, patch, fuzz, show traces
```

## What the demo does

1. Builds `libFuzzer.a` with e9 trace support (`FuzzerE9Trace.cpp`)
2. Compiles `test_focus.cpp` fuzz target with `-O1 -fno-inline -fno-optimize-sibling-calls -rdynamic`
3. Compiles the e9patch hook (`hook_integrated.c`)
4. Patches all `call` instructions in the binary via `e9tool -M 'asm=/call.*/'`
5. Runs the patched fuzzer with `-focus_functions` and `-trace_output_dir`
6. Prints captured JSON traces showing ordered function call sequences

## Example output

```json
{
  "input_hash": "0000000000017410",
  "input_size": 4,
  "path": [
    {"func": "func_apple",  "call_id": 1, "bb": 94226077886160},
    {"func": "func_banana", "call_id": 1, "bb": 94226077886192},
    {"func": "func_cherry", "call_id": 1, "bb": 94226077886224}
  ]
}
```

This is the same JSON format that `-crash_path_file` consumes for
`ComputePathDistance()`, so crash-path-directed fuzzing now works on
real ordered data.

## Architecture

```
 e9patch hook (hook_integrated.c)         libFuzzer (FuzzerE9Trace.cpp)
 ================================         ============================
                                          e9_trace_reset()
                                            ↓ zeros shared buffer
 entry(target, &e9_trace_buf)             ExecuteCallback()
   ↓ writes to shared buffer                ↓ runs target code
   ↓ (called on every `call`                ↓ hook fires for each call
   ↓  instruction at runtime)               ↓
                                          CollectE9Trace()
                                            ↓ reads buffer
                                            ↓ resolves addresses to names
                                            ↓ populates CurrentExecutionPath
                                          ComputePathDistance()
                                            ↓ compares against CrashPath
                                          DumpCurrentPath()
                                            ↓ writes JSON trace file
```

The hook and libFuzzer share the `e9_trace_buf` global. The hook writes
events (target address, sequence number, call count). libFuzzer reads
them and matches target addresses against the focus function symbol table
built at startup via `dladdr`.

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | Clone and build e9patch (one time) |
| `run_integrated.sh` | Full demo: build everything, patch, fuzz, show traces |
| `run.sh` | Standalone demo: toy target without libFuzzer integration |
| `hook.c` | Standalone hook (writes to stderr for debugging) |
| `hook_integrated.c` | Integrated hook (writes to shared memory buffer) |
| `target.c` | Toy target for standalone testing |
| `resolve_trace.py` | Post-process standalone traces (address to name via nm) |

## Files added to libFuzzer (in project root)

| File | Purpose |
|------|---------|
| `FuzzerE9Trace.h` | Shared C header defining the trace buffer struct |
| `FuzzerE9Trace.cpp` | Buffer implementation (reset, record, symbol table) |

## Files modified in libFuzzer

| File | What changed |
|------|-------------|
| `FuzzerTracePC.h` | Added `CollectE9Trace()` and `InitE9SymbolTable()` methods |
| `FuzzerTracePC.cpp` | Added e9 trace collection, `dladdr` fallback for function name resolution, `GetFunctionName()` helper |
| `FuzzerLoop.cpp` | Added `e9_trace_reset()` before execution, `CollectE9Trace()` after execution, `InitE9SymbolTable()` at startup |

## Build requirements

- **clang/clang++** for compiling the fuzz target
- **gcc** for compiling the e9patch hook (e9compile.sh uses gcc)
- **e9patch** (cloned and built by setup.sh)
- Fuzz target must be built with:
  - `-fno-inline` — prevents function inlining so `call` instructions exist
  - `-fno-optimize-sibling-calls` — prevents tail-call optimization (`jmp` instead of `call`)
  - `-rdynamic` — exports symbols so `dladdr` can resolve function names
  - `-ldl` — links the dl library for `dladdr`/`dlsym`

## e9tool matching

The hook is patched onto `call` instructions using:
```
e9tool -M 'asm=/call.*/' -P 'entry(target,&e9_trace_buf)@hook_integrated' binary
```

- `asm=/call.*/` — matches all `call` instructions (regex MUST include `.*`)
- `target` — e9tool passes the runtime call target address
- `&e9_trace_buf` — e9tool passes the runtime address of the global buffer symbol

## Known issues

- **Regex syntax**: `asm=/call/` does NOT work. Must use `asm=/call.*/`.
- **F.name matching**: `F.name=/funcname.*/` patches but hook never fires. Cause unknown. Workaround: `asm` matching.
- **-O1 inlines**: Small functions get inlined at `-O1`+. Use `-fno-inline` and `-fno-optimize-sibling-calls`.
- **call_id accumulates**: The hook's per-target call counter does not reset between fuzzer executions. `e9_trace_reset()` resets `num_events` but the hook maintains its own internal counters. Fix: move call counting into `FuzzerE9Trace.cpp` (already done for the integrated path).
- **ASan incompatible**: ASan + e9patch trampolines conflict. Use without ASan for now.

## Next steps

1. Fix call_id accumulation — the hook's internal `call_counts` should be reset per execution
2. Try `F.entry==true` matching to solve the inlining/tail-call problem
3. Performance: only patch `call` instructions in the target code region, not libFuzzer internals
4. Test with real ARVO/libxml2 targets
