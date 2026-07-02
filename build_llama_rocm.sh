#!/bin/bash
set -e

TAG="master"
CACHE_DIR="/home/tonym/.cache/cerberai"
BUILD_DIR="$CACHE_DIR/llama_build"
BIN_DIR="$CACHE_DIR/bin"

echo "=== Building llama.cpp with ROCm (hipBLAS) Support ==="
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Clean up previous clone to ensure a fresh build of the master branch (ROCm 7.2 compatible)
if [ -d "llama.cpp" ]; then
    echo "Cleaning up previous llama.cpp directory..."
    rm -rf llama.cpp
fi

echo "Cloning llama.cpp repository (branch: $TAG)..."
git clone --depth 1 --branch "$TAG" https://github.com/ggml-org/llama.cpp.git

cd llama.cpp

echo "Configuring build with CMake..."
rm -rf build
mkdir -p build
cd build

export HIPCXX="$(hipconfig -l)/clang++"
export HIP_PATH="$(hipconfig -R)"
export CC=/opt/rocm/llvm/bin/clang
export CXX=/opt/rocm/llvm/bin/clang++

# For newer versions of llama.cpp, GGML_HIP=ON is the correct flag.
# We also pass GGML_HIPBLAS=ON for older/intermediate branches just in case.
cmake .. -DGGML_HIP=ON -DGGML_HIPBLAS=ON -DCMAKE_BUILD_TYPE=Release

echo "Building llama-server target..."
cmake --build . --target llama-server --config Release -j$(nproc)

echo "Copying binaries to target cache..."
mkdir -p "$BIN_DIR"
cp bin/llama-server "$BIN_DIR/llama-server"
# Copy any compiled shared libraries if they exist
find . -name "*.so*" -exec cp {} "$BIN_DIR/" \; 2>/dev/null || true

echo "=== llama.cpp ROCm Build Complete ==="
