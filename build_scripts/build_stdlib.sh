#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

# HARD clean: remove any old objects + archive
rm -f *.o libFuzzer.a
find . -name '*.o' -delete

# Compile with clang + libc++ ABI (CXXFLAGS already contains -stdlib=libc++)
# Include ASan since you're linking ASan builds.
XRAY_FLAGS=""
if [ "${ENABLE_XRAY:-0}" = "1" ]; then
  XRAY_FLAGS="${XRAY_FLAGS:--fxray-instrument -fxray-instruction-threshold=1}"
fi
clang++ -O1 -fno-omit-frame-pointer -gline-tables-only -DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION \
  -stdlib=libc++ -fsanitize=address $XRAY_FLAGS -c *.cpp

# Archive with LLVM tools if available (preferred), otherwise ar/ranlib is fine
command -v llvm-ar >/dev/null && llvm-ar rcs libFuzzer.a *.o || ar rcs libFuzzer.a *.o
command -v llvm-ranlib >/dev/null && llvm-ranlib libFuzzer.a || ranlib libFuzzer.a
