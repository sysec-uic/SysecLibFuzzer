set -eu

export LIB_FUZZING_ENGINE=/SysecLibFuzzer/libFuzzer.a

cd /src/libxml2/fuzz
export OUT=/out

CC="${CC:-clang}"
CXX="${CXX:-clang++}"

XRAY_FLAGS="${XRAY_FLAGS:--fxray-instrument -fxray-instruction-threshold=1}"

# Include libxml2 headers (source + generated)
XML2_INC="-I/src/libxml2/include -I/src/libxml2"

strip_sanitizers() {
  # OSS-Fuzz style CFLAGS/CXXFLAGS often include -fsanitize=...; XRay can't be
  # linked together with ASan runtime, so strip sanitizer-related flags here.
  echo "${1:-}" | sed -E \
    -e 's/(^|[[:space:]])-fsanitize=[^[:space:]]+/ /g' \
    -e 's/(^|[[:space:]])-fno-sanitize=[^[:space:]]+/ /g' \
    -e 's/(^|[[:space:]])-fsanitize-coverage=[^[:space:]]+/ /g' \
    -e 's/[[:space:]]+/ /g' \
    -e 's/^ //; s/ $//'
}

strip_problematic_link_flags() {
  # Some build environments set flags that disable default C++ stdlib linkage,
  # which breaks linking libFuzzer.a unless we re-add the libraries manually.
  echo "${1:-}" | sed -E \
    -e 's/(^|[[:space:]])-nostdlib\\+\\+([[:space:]]|$)/ /g' \
    -e 's/(^|[[:space:]])-nodefaultlibs([[:space:]]|$)/ /g' \
    -e 's/(^|[[:space:]])-nostdlib([[:space:]]|$)/ /g' \
    -e 's/[[:space:]]+/ /g' \
    -e 's/^ //; s/ $//'
}

CFLAGS_NO_SAN="$(strip_sanitizers "${CFLAGS:-}")"
CXXFLAGS_NO_SAN="$(strip_sanitizers "${CXXFLAGS:-}")"
LDFLAGS_NO_SAN="$(strip_sanitizers "${LDFLAGS:-}")"

# Drop flags that prevent auto-linking the C++ standard library.
CXXFLAGS_NO_SAN="$(strip_problematic_link_flags "$CXXFLAGS_NO_SAN")"
LDFLAGS_NO_SAN="$(strip_problematic_link_flags "$LDFLAGS_NO_SAN")"

# Detect which C++ standard library the environment expects (OSS-Fuzz commonly
# uses libc++) so we can rebuild libFuzzer.a with a compatible ABI.
USES_LIBCXX=0
case " $CXXFLAGS_NO_SAN $LDFLAGS_NO_SAN " in
  *" -stdlib=libc++ "*) USES_LIBCXX=1 ;;
esac

# Ensure the fuzzing engine archive is not ASan-instrumented (otherwise it will
# require ASan runtime at link time).
NEED_REBUILD_LIBFUZZER=0
if command -v nm >/dev/null 2>&1; then
  if nm "$LIB_FUZZING_ENGINE" 2>/dev/null | grep -q "__asan_"; then
    NEED_REBUILD_LIBFUZZER=1
  fi
  # ABI mismatch: libc++ uses std::__1, libstdc++ uses std::__cxx11.
  if [ "$USES_LIBCXX" = "1" ] && nm -C "$LIB_FUZZING_ENGINE" 2>/dev/null | grep -q "std::__cxx11"; then
    NEED_REBUILD_LIBFUZZER=1
  fi
  if [ "$USES_LIBCXX" = "0" ] && nm -C "$LIB_FUZZING_ENGINE" 2>/dev/null | grep -q "std::__1"; then
    NEED_REBUILD_LIBFUZZER=1
  fi
fi
# If the archive is older than the source, rebuild so recent changes (e.g.
# symbolization fixes) are picked up.
if [ -f "$LIB_FUZZING_ENGINE" ] && command -v find >/dev/null 2>&1; then
  if find /SysecLibFuzzer -maxdepth 1 -name '*.cpp' -newer "$LIB_FUZZING_ENGINE" | grep -q .; then
    NEED_REBUILD_LIBFUZZER=1
  fi
fi
if [ "$NEED_REBUILD_LIBFUZZER" = "1" ]; then
  if [ "$USES_LIBCXX" = "1" ]; then
    echo "INFO: Rebuilding libFuzzer.a without ASan and with libc++ ABI (USE_LIBCXX=1) for XRay..."
    (cd /SysecLibFuzzer && USE_LIBCXX=1 CXX="$CXX" build_scripts/build.sh)
  else
    echo "INFO: Rebuilding libFuzzer.a without ASan for XRay..."
    (cd /SysecLibFuzzer && CXX="$CXX" build_scripts/build.sh)
  fi
fi

# Ensure libxml2 is built without ASan and with XRay instrumentation; otherwise
# you will get undefined references to __asan_* when linking without ASan.
LIBXML2_A="../.libs/libxml2.a"
if command -v nm >/dev/null 2>&1 && [ -f "$LIBXML2_A" ] && nm "$LIBXML2_A" 2>/dev/null | grep -q "__asan_"; then
  echo "INFO: $LIBXML2_A is ASan-instrumented; rebuilding libxml2 without sanitizers for XRay..."
  JOBS="$(command -v nproc >/dev/null 2>&1 && nproc || echo 4)"
  (cd /src/libxml2 && make clean || true)
  (cd /src/libxml2 && make -j"$JOBS" \
    CC="$CC" CFLAGS="$CFLAGS_NO_SAN $XRAY_FLAGS" \
    CXX="$CXX" CXXFLAGS="$CXXFLAGS_NO_SAN $XRAY_FLAGS")
fi

# Compile objects with XRay (no ASan)
$CC $CFLAGS_NO_SAN $XRAY_FLAGS $XML2_INC -c reader.c fuzz.c

# Link without -fsanitize=address to avoid ASan/XRay runtime conflicts
$CXX $CXXFLAGS_NO_SAN $LDFLAGS_NO_SAN $XRAY_FLAGS $XML2_INC \
  reader.o fuzz.o \
  -o $OUT/reader2 \
  -Wl,--export-dynamic \
  -Wl,--whole-archive $LIB_FUZZING_ENGINE -Wl,--no-whole-archive \
  ../.libs/libxml2.a -Wl,-Bstatic -lz -llzma -Wl,-Bdynamic \
  -pthread -ldl
