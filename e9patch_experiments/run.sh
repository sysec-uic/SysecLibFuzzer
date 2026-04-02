#!/bin/bash
# Build target, compile hook, patch call instructions, run, and resolve trace.
# Usage: ./run.sh [input_string]
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
E9="$SCRIPT_DIR/e9patch"
INPUT="${1:-ABCDEFGH}"

if [ ! -x "$E9/e9tool" ]; then
    echo "e9patch not found. Run ./setup.sh first."
    exit 1
fi

echo "=== Building target (-O0 so calls are not inlined) ==="
clang -O0 -g -o "$SCRIPT_DIR/target_bin" "$SCRIPT_DIR/target.c"

echo "=== Compiling hook ==="
cp "$SCRIPT_DIR/hook.c" "$E9/hook.c"
(cd "$E9" && ./e9compile.sh hook.c)

echo "=== Patching call instructions ==="
"$E9/e9tool" \
    -M 'asm=/call.*/' \
    -P "entry(target)@$E9/hook" \
    "$SCRIPT_DIR/target_bin" \
    -o "$SCRIPT_DIR/target_patched"

echo ""
echo "=== Running patched binary with input: $INPUT ==="
"$SCRIPT_DIR/target_patched" "$INPUT" 2>"$SCRIPT_DIR/trace.log"

echo ""
echo "=== Raw trace ==="
cat "$SCRIPT_DIR/trace.log"

echo ""
echo "=== Resolved trace ==="
python3 "$SCRIPT_DIR/resolve_trace.py" "$SCRIPT_DIR/target_bin" "$SCRIPT_DIR/trace.log"
