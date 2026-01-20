# Focus/Path Tracing Notes

## What changed
- Added focus bias flags to steer fuzzing toward `-focus_functions`:
  - `-focus_require_hit=1` rejects inputs that hit zero focus functions.
  - `-focus_add_if_hit=1` force-adds inputs that touch focus functions even without new coverage.
- Added trace volume control:
  - `-trace_only_on_corpus=1` writes JSON traces only when an input is added to the corpus (crash/exit still dump).
- Crash/exit now flush the in-memory path before dying.
- Reverted the `trace-pc-guard` attempt; path tracing is back to counter-based recording (function hit → `call_id` is 1 per input). No per-call order until a non-recursive guard hook is designed.

## Prior issues
- Using `-focus_function` alone produced no traces; fixed by mapping it through `SetFocusFunctions`.
- Path state leaked across inputs; now reset per input.
- Traces only dumped on corpus additions; now also on crash/exit (and optionally per exec).
- Attempted `trace-pc-guard` per-call tracing caused recursive callbacks and stack overflows due to instrumented symbolization; reverted.
- Empty traces / no corpus growth when `-focus_require_hit=1` and function names didn’t match symbolized names.

## How tracing works now
- Counter-based: after each execution we see which focus-function counters fired; each focus function appears once per input with `call_id=1`.
- `-trace_output_dir` enables JSON dumps; file count depends on `-trace_only_on_corpus`.
- Paths include only functions listed in `-focus_functions` (or `-focus_function` reused).
- `-crash_path_file` + `-path_distance_threshold` filter corpus additions by similarity to a reference path.

## New flags
- `-trace_only_on_corpus=0|1`: dump traces per exec (0) or only when added to corpus/crash (1).
- `-focus_require_hit=0|1`: if 1, reject inputs that hit zero focus functions.
- `-focus_add_if_hit=0|1`: if 1, force-add inputs that hit focus functions even without new coverage.

## Usage examples
Record a PoC path (single run, even if it crashes):
```
./reader2 pocdir \
  -focus_functions=xmlParseChunk \
  -trace_output_dir=/tmp/xml-traces-poc \
  -trace_only_on_corpus=0 \
  -ignore_crashes=1 -fork=1 -runs=1
```

Fuzz toward focus functions, reduced trace volume:
```
./reader2 ../corpus \
  -focus_functions=xmlParseChunk,xmlParseDocument \
  -trace_output_dir=/tmp/xml-traces \
  -trace_only_on_corpus=1 \
  -focus_require_hit=1 \
  -focus_add_if_hit=1 \
  -runs=0
```

Fuzz near a crash path:
```
./reader2 ../corpus \
  -focus_functions=xmlParseChunk,xmlParseDocument \
  -crash_path_file=/tmp/xml-traces-poc/<hash>.json \
  -path_distance_threshold=3 \
  -trace_output_dir=/tmp/xml-traces \
  -trace_only_on_corpus=1 \
  -focus_require_hit=1 \
  -focus_add_if_hit=1
```

## Tips
- Make sure focus function names match symbolized names (no `in ` prefix, strip `()`); check with `nm -C /out/reader2 | grep name`.
- If nothing hits your focus list, relax `-focus_require_hit` and set `-trace_only_on_corpus=0` briefly to see what’s being executed.
- `call_id` stays 1 per function per input until a safe per-call hook is implemented.

## Timeline (high level)
- Build fixes: `build.sh`/`build2.sh` now default to `clang++`, add header include fallbacks; libc++ opt-in via `USE_LIBCXX`.
- Path tracing fixes: map `-focus_function` into multi-function tracer; reset path per input; always walk PCs; dump on crash/exit.
- Guard attempt: added `trace-pc-guard` per-call tracing; caused recursive callbacks/stack overflow; fully reverted to counter-based tracing.
- New controls: `trace_only_on_corpus`, `focus_require_hit`, `focus_add_if_hit` to reduce trace volume and bias toward focus functions; crash/exit path flush added.
- Behavior note: counter-based tracing → one entry per focus function per input (`call_id=1`); no per-call ordering until a non-recursive hook is designed.
