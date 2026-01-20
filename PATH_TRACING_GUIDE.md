# Path Tracing with Call Counting - Implementation Guide

## Overview

This implementation adds path-aware fuzzing with call-instance tracking to libFuzzer. It allows you to:

1. **Record execution paths** with precise call IDs (1st call, 2nd call, etc.)
2. **Activate tracing at specific points** (e.g., "7th call to validate_input")
3. **Compare paths to crash paths** and prioritize similar inputs
4. **Dump detailed traces** for offline analysis

## Flag Quick Reference (new)

- `-focus_functions=func1,func2,...` (required): functions we track; tracing ignores everything else. Names must match symbolized names (see `nm`/`llvm-symbolizer` output). Disables entropic schedule just like `-focus_function`.
- `-trace_output_dir=/path` (recommended): turn on path recording and dump JSON traces there when new corpus items are added.
- `-trigger_point=func:call_id` (optional): start recording only at the Nth call to `func` (1-based). Without it, recording starts immediately.
- `-crash_path_file=/path/to/json` (optional): load a reference crash trace (produced by `-trace_output_dir`) and prefer inputs similar to it.
- `-path_distance_threshold=N` (default 10): when a crash path is loaded, drop inputs whose path distance exceeds N.
- Legacy single-function mode still exists: `-focus_function=name` (but path tracing is designed for `-focus_functions`).

## Files Modified

### 1. FuzzerFlags.def
Added new flags:
- `trace_output_dir`: Directory for path trace JSON files
- `trigger_point`: Activate tracing at specific function call (format: `func:N`)
- `crash_path_file`: Load crash path for comparison
- `path_distance_threshold`: Maximum distance from crash path to keep inputs

### 2. FuzzerOptions.h
Added members to store flag values

### 3. FuzzerTracePC.h
Added:
- `FunctionCallInstance` struct (func_name, call_id, basic_block_id)
- Path recording methods
- Trigger point activation
- Crash path loading and distance computation

### 4. FuzzerTracePC.cpp
Implemented:
- `SetTriggerPoint()`: Set activation point
- `StartPathRecording()`: Begin recording
- `RecordFunctionCall()`: Record each call with ID
- `DumpCurrentPath()`: Save trace to JSON
- `LoadCrashPath()`: Parse crash trace file
- `ComputePathDistance()`: Edit distance from crash path
- Modified `UpdateObservedPCs()` to call recording logic

### 5. FuzzerDriver.cpp
Wire up new flags to Options struct

### 6. FuzzerLoop.cpp
- Initialize path tracing on startup
- Parse trigger point
- Load crash path
- Dump traces and filter by distance in corpus update

## Usage Examples

### Activation Checklist
- Build with symbols (`-g`) so function names survive and match your `-focus_functions` list.
- Always pass `-focus_functions=...` when using path tracing; tracing only records those functions.
- Add `-trace_output_dir=/path` to actually emit traces.
- Optional: add `-trigger_point` to delay tracing, and `-crash_path_file`/`-path_distance_threshold` to bias toward a known crash path.

### Example 1: Record All Execution Paths

```bash
./fuzzer corpus/ \
  -focus_functions=parse_header,decode_frame,validate_input \
  -trace_output_dir=/out/traces \
  -runs=10000
```

This will generate JSON files in `/out/traces/` like:
```json
{
  "input_hash": "abc123...",
  "input_size": 100,
  "path": [
    {"func": "parse_header", "call_id": 1, "bb": 42},
    {"func": "decode_frame", "call_id": 1, "bb": 78},
    {"func": "decode_frame", "call_id": 2, "bb": 81},
    {"func": "validate_input", "call_id": 1, "bb": 103}
  ]
}
```

### Example 2: Start Tracing at Specific Point

```bash
./fuzzer corpus/ \
  -focus_functions=parse_header,decode_frame,validate_input \
  -trigger_point=decode_frame:5 \
  -trace_output_dir=/out/traces \
  -runs=10000
```

This activates tracing only when `decode_frame` is called for the 5th time, reducing overhead.

### Example 3: Fuzz Around Crash Path

```bash
# Step 1: Extract crash path from PoC
./fuzzer crash_input \
  -focus_functions=func1,func2,func3 \
  -trace_output_dir=/tmp \
  -runs=1

# Step 2: Fuzz with path-guided mutation
./fuzzer corpus/ \
  -focus_functions=func1,func2,func3 \
  -crash_path_file=/tmp/crash_trace.json \
  -path_distance_threshold=3 \
  -runs=100000
```

Only keeps inputs within 3 function calls of the crash path.

### Example 4: Combined - Trigger + Crash Path

```bash
./fuzzer corpus/ \
  -focus_functions=parse_header,decode_frame,validate_input \
  -trigger_point=validate_input:7 \
  -crash_path_file=crash.json \
  -path_distance_threshold=2 \
  -trace_output_dir=/out/traces \
  -runs=100000
```

## Workflow

### 1. Extract Crash Path from PoC

```bash
# Run PoC once to get its execution path
./fuzzer poc_crash_input \
  -focus_functions=func_a,func_b,func_c \
  -trace_output_dir=/tmp/crash_trace \
  -runs=1

# This generates: /tmp/crash_trace/<hash>.json
cp /tmp/crash_trace/*.json crash_path.json
```

### 2. Identify Trigger Point

Open `crash_path.json` and find where the interesting execution starts:
```json
{
  "path": [
    {"func": "func_a", "call_id": 1, "bb": 10},
    {"func": "func_a", "call_id": 2, "bb": 12},
    ...
    {"func": "func_b", "call_id": 7, "bb": 45},  ← Trigger here
    {"func": "func_c", "call_id": 1, "bb": 89},  ← Crash nearby
  ]
}
```

Set trigger: `-trigger_point=func_b:7`

### 3. Fuzz Around Crash

```bash
./fuzzer corpus/ \
  -focus_functions=func_a,func_b,func_c \
  -trigger_point=func_b:7 \
  -crash_path_file=crash_path.json \
  -path_distance_threshold=2 \
  -trace_output_dir=/out/similar_traces \
  -max_total_time=600
```

### 4. Analyze Divergent Inputs

```python
# compare_traces.py
import json
import glob

crash = json.load(open("crash_path.json"))["path"]

for trace_file in glob.glob("/out/similar_traces/*.json"):
    trace = json.load(open(trace_file))["path"]

    for i in range(min(len(crash), len(trace))):
        if crash[i] != trace[i]:
            print(f"{trace_file} diverges at step {i}:")
            print(f"  Crash: {crash[i]}")
            print(f"  Input: {trace[i]}")
            break
```

### 5. Use GDB at Exact Divergence

From comparison above, suppose divergence is at "func_b call #7":

```bash
gdb --args ./fuzzer divergent_input.bin

(gdb) break func_b if call_counter==7
(gdb) run
(gdb) print *all_variables
```

## Path Distance Metric

Distance = number of mismatched calls + |length difference|

Example:
```
Crash path: [A:1, B:1, C:1, D:1]
Input path: [A:1, B:1, X:1, D:1]
Distance = 1 (C:1 vs X:1)

Crash path: [A:1, B:1, C:1]
Input path: [A:1, B:1, C:1, D:1, E:1]
Distance = 2 (missing D:1 and E:1)
```

## Performance

- **Without trigger point**: ~5-10% overhead (always counting)
- **With trigger point**: ~1-2% overhead until triggered, then 5-10%
- **Path dumping**: Negligible (only for new corpus additions)

## Limitations

1. Only tracks functions in `-focus_functions` list
2. Basic block ID is PC table index, not source line number
3. JSON parser in LoadCrashPath is simple (no nested objects)
4. Path distance is edit distance (not considering execution semantics)

## Next Steps

After path tracing, use the divergence points with GDB for variable extraction:

```bash
# Found: divergence at func_b call #7
gdb -x extract_vars.py --args ./fuzzer input.bin
```

See `PATH_TRACING_GUIDE.md` for full workflow integration with GDB.
