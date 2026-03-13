#!/bin/bash
set -e

echo "=== 1. Check & Install Dependencies ==="
echo "Requesting sudo permission to install build tools..."
sudo apt-get update
sudo apt-get install -y git help2man perl python3 make autoconf g++ flex bison ccache libgoogle-perftools-dev numactl perl-doc libfl-dev zlib1g-dev

echo "=== 2. Clone Verilator Repository ==="
if [ -d "verilator" ]; then
    echo "Directory 'verilator' already exists. Removing it to ensure clean build..."
    rm -rf verilator
fi
git clone https://github.com/verilator/verilator

echo "=== 3. Checkout Version v5.044 ==="
unset VERILATOR_ROOT
cd verilator
git checkout v5.044

echo "=== 4. Build & Install ==="
autoconf
./configure
make -j $(nproc)
echo "Installing to system (requires sudo)..."
sudo make install

echo "=== 5. Verification ==="
verilator --version

echo "=== Done! ==="
