#!/usr/bin/env bash
# Usage: ./run_all.sh 'C:\ssdtest\bench.fio-testfile' [run_fio.py options, e.g. --fio '/mnt/c/Program Files/fio/fio.exe' --quick --wsl-target ~/ssdtest/x.fio-testfile]
# Windows mode (valid for the real SSD from WSL2): target is a Windows path. Linux mode: target is a path on the NVMe filesystem (native Linux).
set -euo pipefail; cd "$(dirname "$0")"; T=${1:?target file path ending in .fio-testfile}; shift
./ssd_info.sh || true
python3 run_fio.py --target "$T" "$@"
python3 plot_fio.py
