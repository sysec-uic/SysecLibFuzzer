#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LIBFUZZER_SRC_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$LIBFUZZER_SRC_DIR"
# Default to the C++ compiler so standard library headers are found
CXX="${CXX:-clang++}"
# XRay instrumentation for libFuzzer itself is optional and usually unnecessary.
# Keeping libFuzzer uninstrumented avoids recursion hazards in the XRay handler
# and keeps traces focused on the target.
XRAY_FLAGS=""
if [ "${ENABLE_XRAY:-0}" = "1" ]; then
  XRAY_FLAGS="${XRAY_FLAGS:--fxray-instrument -fxray-instruction-threshold=1}"
fi
# Opt-in flag: set USE_LIBCXX=1 to build against libc++; otherwise libstdc++ is used.
STD_LIB_FLAGS=""
if [ "${USE_LIBCXX:-0}" = "1" ]; then
  STD_LIB_FLAGS="-stdlib=libc++"
fi

# Fallback: if clang selects a GCC version without headers installed (common on
# minimal images), point it at the newest libstdc++ headers we can find.
STDINC_FLAGS="${STDINC_FLAGS:-}"
if [ -z "$STDINC_FLAGS" ]; then
  if [ "${USE_LIBCXX:-0}" = "1" ]; then
    if [ -d "/usr/include/c++/v1" ]; then
      STDINC_FLAGS="-isystem /usr/include/c++/v1"
    fi
  else
    STDINC_VERSION=$(ls -1 /usr/include/c++ 2>/dev/null | grep -E '^[0-9]+' | sort -V | tail -1)
    if [ -n "$STDINC_VERSION" ] && [ -d "/usr/include/c++/$STDINC_VERSION" ]; then
      STDINC_FLAGS="-isystem /usr/include/c++/$STDINC_VERSION"
      if [ -d "/usr/include/x86_64-linux-gnu/c++/$STDINC_VERSION" ]; then
        STDINC_FLAGS="$STDINC_FLAGS -isystem /usr/include/x86_64-linux-gnu/c++/$STDINC_VERSION"
      fi
    fi
  fi
fi

for f in $LIBFUZZER_SRC_DIR/*.cpp; do
  $CXX -g -O2 -fno-omit-frame-pointer -std=c++17 \
    $STD_LIB_FLAGS $STDINC_FLAGS $XRAY_FLAGS $f -c &
done
wait
rm -f libFuzzer.a
ar r libFuzzer.a Fuzzer*.o
rm -f Fuzzer*.o
