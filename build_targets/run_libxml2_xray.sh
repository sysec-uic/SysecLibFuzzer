# compile objects with XRay
$CXX $CXXFLAGS -fxray-instrument -fxray-instruction-threshold=1 -c reader.c fuzz.c

# link without -fsanitize=address
$CXX $CXXFLAGS \
  reader.o fuzz.o \
  -o $OUT/reader2 \
  -Wl,--whole-archive $LIB_FUZZING_ENGINE -Wl,--no-whole-archive \
  ../.libs/libxml2.a -Wl,-Bstatic -lz -llzma -Wl,-Bdynamic \
  -pthread -ldl

