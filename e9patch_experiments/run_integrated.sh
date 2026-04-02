#!/bin/bash
# End-to-end demo: e9patch trace integration with libFuzzer.
#
# What this does:
#   1. Builds libFuzzer.a (with e9 trace support)
#   2. Compiles the test_focus fuzz target
#   3. Compiles the e9patch hook
#   4. Patches the fuzz target binary with the hook
#   5. Runs the patched fuzzer with focus functions and trace output
#   6. Prints the captured execution traces
#
# Usage: ./run_integrated.sh
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJ_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
E9_DIR="$SCRIPT_DIR/e9patch"
OUT_DIR="/tmp/e9_integrated_demo"

# Check e9patch
if [ ! -x "$E9_DIR/e9tool" ]; then
    echo "e9patch not found. Run ./setup.sh first."
    exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/corpus" "$OUT_DIR/traces"

# --- Step 1: Build libFuzzer.a ---
echo "=== Step 1: Building libFuzzer.a ==="
(cd "$PROJ_DIR" && ./build_scripts/build.sh)
echo "   -> $PROJ_DIR/libFuzzer.a"

# --- Step 2: Build fuzz target ---
echo ""
echo "=== Step 2: Building fuzz target ==="
echo "   Flags: -O1 -fno-inline -fno-optimize-sibling-calls -rdynamic"
clang++ -O1 -fno-inline -fno-optimize-sibling-calls -g \
    -fsanitize=fuzzer-no-link -std=c++17 \
    "$PROJ_DIR/custom_tests/test_focus.cpp" \
    -c -o "$OUT_DIR/test_focus.o"

clang++ -O1 -fno-inline -fno-optimize-sibling-calls -g -rdynamic \
    "$OUT_DIR/test_focus.o" "$PROJ_DIR/libFuzzer.a" \
    -lstdc++ -lpthread -ldl \
    -o "$OUT_DIR/fuzz_target"
echo "   -> $OUT_DIR/fuzz_target"

# --- Step 3: Compile e9patch hook ---
echo ""
echo "=== Step 3: Compiling e9patch hook ==="
cp "$SCRIPT_DIR/hook_integrated.c" "$E9_DIR/hook_integrated.c"
(cd "$E9_DIR" && ./e9compile.sh hook_integrated.c)
echo "   -> $E9_DIR/hook_integrated"

# --- Step 4: Patch the binary ---
echo ""
echo "=== Step 4: Patching binary (hooking all call instructions) ==="
"$E9_DIR/e9tool" \
    -M 'asm=/call.*/' \
    -P "entry(target,&e9_trace_buf)@$E9_DIR/hook_integrated" \
    "$OUT_DIR/fuzz_target" \
    -o "$OUT_DIR/fuzz_target_patched"
echo "   -> $OUT_DIR/fuzz_target_patched"

# --- Step 5: Run the patched fuzzer ---
echo ""
echo "=== Step 5: Running patched fuzzer ==="
echo "ABC" > "$OUT_DIR/corpus/seed1"
echo "XYZ" > "$OUT_DIR/corpus/seed2"
echo "A"   > "$OUT_DIR/corpus/seed3"

timeout 5 "$OUT_DIR/fuzz_target_patched" "$OUT_DIR/corpus" \
    -focus_functions=func_apple,func_banana,func_cherry \
    -trace_output_dir="$OUT_DIR/traces" \
    -trace_only_on_corpus=0 \
    -runs=20 \
    2>&1 || true

# --- Step 6: Show traces ---
echo ""
echo "=== Step 6: Captured traces ==="
TRACE_COUNT=$(ls "$OUT_DIR/traces/"*.json 2>/dev/null | wc -l)
echo "   $TRACE_COUNT trace files in $OUT_DIR/traces/"
echo ""
for f in "$OUT_DIR/traces/"*.json; do
    [ -f "$f" ] || continue
    echo "--- $(basename "$f") ---"
    cat "$f"
    echo ""
done
