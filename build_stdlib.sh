cd /SysecLibFuzzer

# HARD clean: remove any old objects + archive
rm -f *.o libFuzzer.a
find . -name '*.o' -delete

# Compile with clang + libc++ ABI (CXXFLAGS already contains -stdlib=libc++)
# Include ASan since you're linking ASan builds.
clang++ -O1 -fno-omit-frame-pointer -gline-tables-only -DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION \
  -stdlib=libc++ -fsanitize=address  -c *.cpp

# Archive with LLVM tools if available (preferred), otherwise ar/ranlib is fine
command -v llvm-ar >/dev/null && llvm-ar rcs libFuzzer.a *.o || ar rcs libFuzzer.a *.o
command -v llvm-ranlib >/dev/null && llvm-ranlib libFuzzer.a || ranlib libFuzzer.a

