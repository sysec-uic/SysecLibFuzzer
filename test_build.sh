# this is a custom build files that will be used to ensure that the libfuzzer will build
# there seems to be some issues related to stdlib, this build is made to ensure this issues
# is resolved
#
# authord by Kenan on Clang version (18.3)
#
#
#
#!/bin/sh

#set -e
#!/bin/sh
LIBFUZZER_SRC_DIR=$(dirname $0)
CXX="${CXX:-clang}"
for f in $LIBFUZZER_SRC_DIR/*.cpp; do
  $CXX -g -O2 -fno-omit-frame-pointer -std=c++17 $f -c &
done
wait
rm -f libFuzzer.a
ar r libFuzzer.a Fuzzer*.o
rm -f Fuzzer*.o
