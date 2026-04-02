#!/bin/bash
# End-to-end demo: e9patch tracing on libxml2 fuzzer inside Docker.
# Builds everything from scratch, runs the fuzzer, shows traces.
# Usage: ./docker-e9/run_demo.sh
set -eu

PROJ_DIR=$(cd "$(dirname "$0")/.." && pwd)
IMAGE="sysec-libfuzzer-e9"
TRACES="/tmp/libxml2_traces"
CORPUS="/tmp/libxml2_corpus"
RUNS=500
FOCUS="xmlParseChunk,xmlTextReaderRead,xmlReadMemory,xmlSAX2StartElementNs"

echo "=== Step 1: Building Docker image ==="
# Stop any running container with our name
docker rm -f sysec-e9-demo 2>/dev/null || true
docker build -t "$IMAGE" -f "$PROJ_DIR/docker-e9/Dockerfile" "$PROJ_DIR"

echo ""
echo "=== Step 2: Creating seed corpus ==="
rm -rf "$TRACES" "$CORPUS"
mkdir -p "$TRACES" "$CORPUS"

python3 -c "
import struct, sys
opts = struct.pack('<i', 0)
sys.stdout.buffer.write(opts + b'test\x5c\x0a' + b'<a b=\"c\"/>\x5c\x0a')
" > "$CORPUS/seed1.bin"

python3 -c "
import struct, sys
opts = struct.pack('<i', 0)
sys.stdout.buffer.write(opts + b'test\x5c\x0a' + b'<root><child>text</child></root>\x5c\x0a')
" > "$CORPUS/seed2.bin"

echo "   2 seed files in $CORPUS"

echo ""
echo "=== Step 3: Running patched fuzzer ($RUNS runs) ==="
docker run --rm \
    -v "$TRACES:/out/traces" \
    -v "$CORPUS:/out/corpus" \
    "$IMAGE" \
    /out/xml_fuzz_patched /out/corpus \
    -focus_functions="$FOCUS" \
    -trace_output_dir=/out/traces \
    -trace_only_on_corpus=0 \
    -runs="$RUNS"

echo ""
TRACE_COUNT=$(ls "$TRACES"/*.json 2>/dev/null | wc -l)
echo "=== Step 4: Results ==="
echo "   $TRACE_COUNT trace files captured in $TRACES/"
echo ""
echo "--- Sample traces ---"
for f in $(ls "$TRACES"/*.json 2>/dev/null | head -3); do
    echo "=== $(basename "$f") ==="
    cat "$f"
    echo ""
done
