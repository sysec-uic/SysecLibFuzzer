#!/bin/bash
# Build and run the libxml2 fuzzer with e9patch tracing inside Docker.
#
# Usage:
#   ./run_libxml2_e9.sh build          # build the Docker image
#   ./run_libxml2_e9.sh fuzz [OPTS]    # run fuzzing with traces
#   ./run_libxml2_e9.sh traces         # show captured traces
#   ./run_libxml2_e9.sh shell          # open a shell in the container
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJ_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
IMAGE="sysec-libfuzzer-e9"
CONTAINER="sysec-e9-fuzz"

# Focus functions from the crash log (crash_log.txt)
FOCUS_FUNCS="xmlIsID,xmlSAX2AttributeNs,xmlSAX2StartElementNs,xmlTextReaderStartElementNs,xmlParseStartTag2,xmlParseTryOrFinish,xmlParseChunk,xmlTextReaderPushData"

case "${1:-help}" in
  build)
    echo "=== Building Docker image ==="
    docker build -t "$IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$PROJ_DIR"
    echo ""
    echo "=== Verifying binaries ==="
    docker run --rm "$IMAGE" ls -la /out/xml_fuzz /out/xml_fuzz_patched
    docker run --rm "$IMAGE" nm /out/xml_fuzz_patched | grep -c 'T xml' | xargs -I{} echo "  {} libxml2 functions in symbol table"
    echo ""
    echo "Done. Run: $0 fuzz"
    ;;

  fuzz)
    shift || true
    RUNS="${1:-100}"
    echo "=== Running patched fuzzer ($RUNS runs) ==="
    docker run --rm --name "$CONTAINER" \
      "$IMAGE" \
      /out/xml_fuzz_patched /out/corpus \
        -focus_functions="$FOCUS_FUNCS" \
        -trace_output_dir=/out/traces \
        -trace_only_on_corpus=0 \
        -runs="$RUNS"
    echo ""
    echo "Done. Run: $0 traces"
    ;;

  traces)
    echo "=== Captured traces ==="
    docker run --rm "$IMAGE" sh -c 'ls /out/traces/*.json 2>/dev/null | wc -l | xargs -I{} echo "{} trace files"'
    docker run --rm "$IMAGE" sh -c 'cat /out/traces/*.json 2>/dev/null | head -100'
    ;;

  shell)
    echo "=== Opening shell ==="
    docker run --rm -it "$IMAGE" /bin/bash
    ;;

  *)
    echo "Usage: $0 {build|fuzz [RUNS]|traces|shell}"
    echo ""
    echo "  build          Build Docker image with libxml2 + e9patch"
    echo "  fuzz [RUNS]    Run patched fuzzer (default 100 runs)"
    echo "  traces         Show captured trace files"
    echo "  shell          Open interactive shell in container"
    ;;
esac
