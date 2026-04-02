#!/bin/bash
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
E9PATCH_DIR="$SCRIPT_DIR/e9patch"

if [ -x "$E9PATCH_DIR/e9patch" ] && [ -x "$E9PATCH_DIR/e9tool" ]; then
    echo "e9patch already built at $E9PATCH_DIR"
    exit 0
fi

echo "=== Cloning e9patch ==="
if [ ! -d "$E9PATCH_DIR" ]; then
    git clone https://github.com/GJDuck/e9patch.git "$E9PATCH_DIR"
fi

echo "=== Building e9patch ==="
cd "$E9PATCH_DIR"
./build.sh

echo "=== Verifying ==="
./e9patch --help | head -1
./e9tool --help | head -1
echo "Done. Binaries at: $E9PATCH_DIR/e9patch and $E9PATCH_DIR/e9tool"
