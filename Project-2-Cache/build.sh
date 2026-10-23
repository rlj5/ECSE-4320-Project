#!/usr/bin/env bash
set -euo pipefail; cd "$(dirname "$0")"; mkdir -p build; CC=${CC:-gcc}
$CC -O2 -march=native -std=gnu11 src/memlat.c -o build/memlat
$CC -O2 -march=native -std=gnu11 -pthread src/membw.c -o build/membw
$CC -O2 -march=native -std=gnu11 -fopenmp src/stream_triad.c -o build/stream_triad
echo built; $CC --version | head -1
