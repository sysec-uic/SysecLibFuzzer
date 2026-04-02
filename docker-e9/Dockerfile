FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Build tools + clang + e9patch deps
RUN apt-get update && apt-get install -y \
    clang lld llvm \
    build-essential gcc g++ \
    git cmake autoconf automake libtool pkg-config \
    python3 \
    zlib1g-dev liblzma-dev \
    markdown xxd \
    && rm -rf /var/lib/apt/lists/*

# Clone and build e9patch
RUN git clone https://github.com/GJDuck/e9patch.git /opt/e9patch \
    && cd /opt/e9patch && ./build.sh

# Clone libxml2 (use a fixed tag for reproducibility)
RUN git clone --depth 1 --branch v2.9.14 https://gitlab.gnome.org/GNOME/libxml2.git /src/libxml2

# Build libxml2 from source with -fno-inline for e9patch compatibility
RUN cd /src/libxml2 \
    && ./autogen.sh \
    && ./configure \
        CC=clang \
        CFLAGS="-O1 -g -fno-inline -fno-optimize-sibling-calls -fno-omit-frame-pointer -fsanitize=fuzzer-no-link" \
        --disable-shared --enable-static \
        --without-python --without-http --without-ftp \
    && make -j$(nproc)

# Copy SysecLibFuzzer into container
COPY . /SysecLibFuzzer

# Copy the ARVO harness (raw XML input, no fuzz format wrapper)
COPY docker-e9/xml_read_memory_fuzzer.cc /src/xml_read_memory_fuzzer.cc

# Build libFuzzer.a
RUN cd /SysecLibFuzzer && ./build_scripts/build.sh

# Compile e9patch hook
RUN cd /opt/e9patch \
    && cp /SysecLibFuzzer/e9patch_experiments/hook_integrated.c . \
    && ./e9compile.sh hook_integrated.c

# Build the fuzz harness (ARVO-style: raw XML input)
RUN mkdir -p /out && clang++ -O1 -g -fno-inline -fno-optimize-sibling-calls \
        -fsanitize=fuzzer-no-link \
        -I/src/libxml2/include -I/src/libxml2 \
        -c /src/xml_read_memory_fuzzer.cc -o /tmp/harness.o \
    && clang++ -O1 -g -fno-inline -fno-optimize-sibling-calls \
        -rdynamic \
        /tmp/harness.o \
        -o /out/xml_fuzz \
        -Wl,--whole-archive /SysecLibFuzzer/libFuzzer.a -Wl,--no-whole-archive \
        /src/libxml2/.libs/libxml2.a \
        -Wl,-Bstatic -lz -llzma -Wl,-Bdynamic \
        -lstdc++ -lpthread -ldl

# Patch the binary with e9patch
RUN /opt/e9patch/e9tool \
    -M 'asm=/call.*/' \
    -P "entry((static)target,&e9_trace_buf)@/opt/e9patch/hook_integrated" \
    /out/xml_fuzz \
    -o /out/xml_fuzz_patched

# Create output dirs
RUN mkdir -p /out/traces /out/corpus /out/crashes

WORKDIR /out
