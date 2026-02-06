# Chat Summary (saved)

This file captures the main points and chronology from the recent discussion.

## Build and toolchain fixes
- Initial builds failed: standard headers like `<cassert>`/`<cstdint>` not found because `build.sh` used `clang` (C compiler) and libc++ headers were missing.
- Fixes: default to `clang++`, add fallback `-isystem` include paths for libstdc++ (and libc++ opt-in via `USE_LIBCXX=1` in `build2.sh`), restore `-std=c++17`. Builds now produce `libFuzzer.a`.

## Path tracing fixes (counter-based)
- `-focus_function` alone produced no traces; now mapped through `SetFocusFunctions`.
- Path state now resets per input; tracing no longer leaks across runs.
- Traces now dump even without new coverage and on crash/exit (best-effort flush).
- Path tracer remains counter-based: each focus function shows up once per input (`call_id=1`); no per-call order yet.

## Documentation
- `PATH_TRACING_GUIDE.md`: added quick reference for path flags and activation checklist.
- `FOCUS_TRACING_NOTES.md`: added summary, new flags, and timeline.

## Trace-pc-guard attempt (reverted)
- Added per-call tracing via `__sanitizer_cov_trace_pc_guard`; caused recursive callbacks/stack overflows because the hook was instrumented and called `DescribePC`.
- Attempts to suppress instrumentation didn’t resolve recursion; reverted to counter-based tracing. Guard hooks now just warn.

## New flags (bias and trace control)
- `-trace_only_on_corpus=1`: dump traces only when an input is added to corpus (crash/exit still dump).
- `-focus_require_hit=1`: reject inputs that hit zero `-focus_functions`.
- `-focus_add_if_hit=1`: force-add inputs that hit focus functions even without new coverage.
- Existing: `-crash_path_file` + `-path_distance_threshold` filter corpus additions by similarity to a reference path.

## Usage examples
- PoC path (single run, even if it crashes):
  ```
  ./reader2 pocdir \
    -focus_functions=xmlParseChunk \
    -trace_output_dir=/tmp/xml-traces-poc \
    -trace_only_on_corpus=0 \
    -ignore_crashes=1 -fork=1 -runs=1
  ```
- Fuzz with focus bias, reduced traces:
  ```
  ./reader2 ../corpus \
    -focus_functions=xmlParseChunk,xmlParseDocument \
    -trace_output_dir=/tmp/xml-traces \
    -trace_only_on_corpus=1 \
    -focus_require_hit=1 \
    -focus_add_if_hit=1
  ```

## Common pitfalls and checks
- Ensure focus function names match symbolized names (strip `in ` prefix / trailing `()`).
- If nothing hits focus functions, relax `-focus_require_hit` and set `-trace_only_on_corpus=0` briefly to see executions.
- One JSON per execution when `trace_only_on_corpus=0`; many files are expected. Set to 1 to reduce volume.
- Using `-focus_require_hit=1` can reject all inputs if focus functions aren’t reached or names don’t match.

## Status
- Current tracer: counter-based (`call_id=1`), bias flags in place, guard-based per-call tracing deferred until a non-recursive hook is designed.
