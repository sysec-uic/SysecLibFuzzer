export LIB_FUZZING_ENGINE=/SysecLibFuzzer/libFuzzer.a


cd /src/libxml2/fuzz
export OUT=/out

$CXX $CXXFLAGS -fsanitize=address \
 reader.o fuzz.o \
  -o $OUT/reader2 \
  -Wl,--whole-archive $LIB_FUZZING_ENGINE -Wl,--no-whole-archive \
  ../.libs/libxml2.a -Wl,-Bstatic -lz -llzma -Wl,-Bdynamic \
  -pthread -ldl

