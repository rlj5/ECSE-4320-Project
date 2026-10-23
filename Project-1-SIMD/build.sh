#!/usr/bin/env bash
# Builds 4 variants of the same source. Vectorization reports go to reports/.
set -euo pipefail
cd "$(dirname "$0")"; mkdir -p build reports
CC=${CC:-gcc}; ARCH=${ARCH:-native}   # on Ryzen 7 5825U (Zen 3) 'native' == znver3: AVX2+FMA, NO AVX-512
b(){ n=$1; shift
  $CC -O3 -std=gnu11 "$@" -DVARIANT="\"$n\"" src/bench.c -o build/bench_$n -lm \
     -fopt-info-vec-all=reports/vec_all_$n.txt; }
b scalar    -fno-tree-vectorize -fno-tree-slp-vectorize      # no SIMD (scalar SSE2 FP math only)
b auto                                                       # default x86-64 baseline => 128-bit SSE2 auto-vectorization
b native    -march=$ARCH                                     # widest ISA of this CPU (AVX2+FMA on Zen3), strict FP semantics
b native_fm -march=$ARCH -ffast-math                         # + reassociation allowed (needed to vectorize reductions)
# loop-alignment twins: same flags + every loop start padded to a 64-byte boundary (tests "loop straddles a 64 B line")
b scalar_al    -fno-tree-vectorize -fno-tree-slp-vectorize -falign-loops=64
b auto_al                                                  -falign-loops=64
b native_al    -march=$ARCH -falign-loops=64
b native_fm_al -march=$ARCH -ffast-math -falign-loops=64
$CC -O2 -march=$ARCH -mavx2 -mfma src/peak_flops.c -o build/peak_flops
$CC --version | head -1 > reports/compiler_version.txt
echo "built: $(ls build | tr '\n' ' ')"
