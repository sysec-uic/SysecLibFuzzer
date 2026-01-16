#!/bin/sh
LIBFUZZER_SRC_DIR=$(dirname $0)
CXX="${CXX:-clang++}"
for f in $LIBFUZZER_SRC_DIR/*.cpp; do
  $CXX -g -O2 -fno-omit-frame-pointer -std=c++17 \
    -O1 -fno-omit-frame-pointer -gline-tables-only \
    -DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION \
    -stdlib=libc++ -fsanitize=address -pthread \
    $f -c &
done
wait
rm -f libFuzzer.a
ar r libFuzzer.a Fuzzer*.o
rm -f Fuzzer*.o
