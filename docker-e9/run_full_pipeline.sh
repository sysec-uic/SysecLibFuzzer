#!/bin/bash
# Full end-to-end pipeline: crash-path-directed fuzzing on libxml2.
#
# What this does:
#   1. Builds Docker image (libxml2 + libFuzzer + e9patch)
#   2. Pulls a real crash PoC from the ARVO database (bug 42470339)
#   3. Runs the PoC through the patched binary to capture the crash execution path
#   4. Fuzzes with the crash path as reference, rejecting inputs that are too different
#
# Prerequisites: docker
# Usage: ./docker-e9/run_full_pipeline.sh
set -eu

PROJ_DIR=$(cd "$(dirname "$0")/.." && pwd)
IMAGE="sysec-libfuzzer-e9"
ARVO_IMAGE="n132/arvo:42470339-vul"
ARVO_ID="42470339"

# Focus functions from the crash stack trace
FOCUS="xmlSAX2StartElementNs,xmlParseElement,xmlParseContent,xmlReadMemory"

# Directories (on host, mounted into container)
POC_DIR="/tmp/e9_pipeline/poc"
CRASH_PATH_DIR="/tmp/e9_pipeline/crash_path"
CORPUS_DIR="/tmp/e9_pipeline/corpus"
TRACES_DIR="/tmp/e9_pipeline/traces"

rm -rf /tmp/e9_pipeline
mkdir -p "$POC_DIR" "$CRASH_PATH_DIR" "$CORPUS_DIR" "$TRACES_DIR"

# =========================================================
echo "=== Step 1: Build Docker image ==="
echo "    (libxml2 + SysecLibFuzzer + e9patch hook)"
echo ""
docker build -t "$IMAGE" -f "$PROJ_DIR/docker-e9/Dockerfile" "$PROJ_DIR"

# =========================================================
echo ""
echo "=== Step 2: Pull crash PoC from ARVO (bug $ARVO_ID) ==="
echo "    Heap-use-after-free in xmlSAX2AttributeNs"
echo ""
docker pull "$ARVO_IMAGE" 2>&1 | tail -3
docker run --rm "$ARVO_IMAGE" cat /tmp/poc > "$POC_DIR/poc.bin"
echo "    PoC: $POC_DIR/poc.bin ($(wc -c < "$POC_DIR/poc.bin") bytes)"
echo "    Content: crafted XML with deeply nested <U> elements"

# =========================================================
echo ""
echo "=== Step 3: Record crash execution path ==="
echo "    Running PoC through e9patch-instrumented binary..."
echo "    Focus functions: $FOCUS"
echo ""

# Use PoC as seed corpus so it goes through RunOne (not RunIndividualFiles)
cp "$POC_DIR/poc.bin" "$CORPUS_DIR/poc.bin"

docker run --rm \
    -v "$CRASH_PATH_DIR:/out/traces" \
    -v "$CORPUS_DIR:/out/corpus" \
    "$IMAGE" \
    /out/xml_fuzz_patched /out/corpus \
    -focus_functions="$FOCUS" \
    -trace_output_dir=/out/traces \
    -trace_only_on_corpus=0 \
    -runs=1 \
    2>&1 | grep -E 'Focus func|symbol|INITED|overflow|DONE'

CRASH_PATH=$(ls "$CRASH_PATH_DIR"/*.json 2>/dev/null | head -1)
if [ -z "$CRASH_PATH" ]; then
    echo "ERROR: No crash path trace generated"
    exit 1
fi

echo ""
echo "    Crash path: $CRASH_PATH"
echo "    Path summary:"
python3 -c "
import json
data = json.load(open('$CRASH_PATH'))
from collections import Counter
counts = Counter(e['func'] for e in data['path'])
print(f'      {len(data[\"path\"])} function calls total')
for func, cnt in counts.most_common():
    print(f'      {func}: {cnt} calls')
print(f'    First 5: ', ', '.join(e['func']+':'+str(e['call_id']) for e in data['path'][:5]))
"

# =========================================================
echo ""
echo "=== Step 4: Fuzz toward the crash path ==="
echo "    Using -crash_path_file to reject inputs with distant paths"
echo "    -path_distance_threshold=50 (allow inputs within 50 steps)"
echo ""

# Copy crash path JSON into a directory the container can access
CRASH_PATH_MOUNT="/tmp/e9_pipeline/crash_ref"
mkdir -p "$CRASH_PATH_MOUNT"
cp "$CRASH_PATH" "$CRASH_PATH_MOUNT/crash.json"

# Create some XML seed inputs
echo '<a/>' > "$CORPUS_DIR/seed1.xml"
echo '<a b="c"><d/></a>' > "$CORPUS_DIR/seed2.xml"
echo '<r><r><r><r></r></r></r></r>' > "$CORPUS_DIR/seed3.xml"

# Clear traces from step 3
rm -rf "$TRACES_DIR"/*

docker run --rm \
    -v "$TRACES_DIR:/out/traces" \
    -v "$CORPUS_DIR:/out/corpus" \
    -v "$CRASH_PATH_MOUNT/crash.json:/out/crash.json:ro" \
    "$IMAGE" \
    /out/xml_fuzz_patched /out/corpus \
    -focus_functions="$FOCUS" \
    -trace_output_dir=/out/traces \
    -trace_only_on_corpus=0 \
    -crash_path_file=/out/crash.json \
    -path_distance_threshold=50 \
    -runs=500 \
    2>&1 | tail -10

# =========================================================
echo ""
echo "=== Results ==="
TRACE_COUNT=$(ls "$TRACES_DIR"/*.json 2>/dev/null | wc -l)
echo "    $TRACE_COUNT traces captured (inputs whose path was within 50 steps of crash)"
echo ""

if [ "$TRACE_COUNT" -gt 0 ]; then
    echo "--- Sample traces (first 3) ---"
    for f in $(ls "$TRACES_DIR"/*.json | head -3); do
        echo ""
        echo "=== $(basename "$f") ==="
        python3 -c "
import json
data = json.load(open('$f'))
print(f'  input: {data.get(\"input_ascii\", \"?\")[:60]}')
print(f'  size: {data[\"input_size\"]} bytes')
print(f'  path: {len(data[\"path\"])} calls')
from collections import Counter
counts = Counter(e['func'] for e in data['path'])
for func, cnt in counts.most_common():
    print(f'    {func}: {cnt}')
"
    done
fi

echo ""
echo "=== Pipeline complete ==="
echo "  PoC:        $POC_DIR/poc.bin"
echo "  Crash path: $CRASH_PATH"
echo "  Traces:     $TRACES_DIR/"
echo "  Corpus:     $CORPUS_DIR/"
