#!/bin/sh
LIBFUZZER_SRC_DIR=$(dirname $0)
# Default to the C++ compiler so standard library headers are found
CXX="${CXX:-clang++}"

# Fallback: if clang selects a GCC version without headers installed (common on
# minimal images), point it at the newest libstdc++ headers we can find.
STDINC_FLAGS="${STDINC_FLAGS:-}"
if [ -z "$STDINC_FLAGS" ]; then
  STDINC_VERSION=$(ls -1 /usr/include/c++ 2>/dev/null | grep -E '^[0-9]+' | sort -V | tail -1)
  if [ -n "$STDINC_VERSION" ] && [ -d "/usr/include/c++/$STDINC_VERSION" ]; then
    STDINC_FLAGS="-isystem /usr/include/c++/$STDINC_VERSION"
    if [ -d "/usr/include/x86_64-linux-gnu/c++/$STDINC_VERSION" ]; then
      STDINC_FLAGS="$STDINC_FLAGS -isystem /usr/include/x86_64-linux-gnu/c++/$STDINC_VERSION"
    fi
  fi
fi

for f in $LIBFUZZER_SRC_DIR/*.cpp; do
  $CXX -g -O2 -fno-omit-frame-pointer -std=c++17 $STDINC_FLAGS $f -c &
done
wait
rm -f libFuzzer.a
ar r libFuzzer.a Fuzzer*.o
rm -f Fuzzer*.o
