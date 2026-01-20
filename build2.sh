#!/bin/sh
LIBFUZZER_SRC_DIR=$(dirname $0)
# Default to the C++ compiler so standard library headers are found
CXX="${CXX:-clang++}"
# Opt-in flag: set USE_LIBCXX=1 to build against libc++; otherwise libstdc++ is used.
STD_LIB_FLAGS=""
if [ "${USE_LIBCXX:-0}" = "1" ]; then
  STD_LIB_FLAGS="-stdlib=libc++"
fi

# Fallback include search path for libstdc++/libc++ headers when clang picks a
# GCC version whose headers are not installed.
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
    -O1 -fno-omit-frame-pointer -gline-tables-only \
    -DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION \
    $STD_LIB_FLAGS $STDINC_FLAGS -fsanitize=address -pthread \
    $f -c &
done
wait
rm -f libFuzzer.a
ar r libFuzzer.a Fuzzer*.o
rm -f Fuzzer*.o
