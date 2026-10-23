#!/usr/bin/env bash
# Pitfall demo (needs root): frequency scaling distorts ns-based results. Runs the same L1/L3 chase at a pinned LOW and HIGH clock.
# Restores the original max frequency afterwards. Output: data/raw/pitfall_freq.csv
set -euo pipefail; cd "$(dirname "$0")"; CPU=${CPU:-0}; P=/sys/devices/system/cpu/cpu$CPU/cpufreq
[ -w $P/scaling_max_freq ] || { echo "run with sudo (needs cpufreq write access)"; exit 1; }
orig=$(cat $P/scaling_max_freq); lo=$(cat $P/cpuinfo_min_freq); hi=$(cat $P/cpuinfo_max_freq); mid=$(( (lo+hi)/2 ))
echo "setting,max_khz,freq_est_ghz,$(./build/memlat --header)" > data/raw/pitfall_freq.csv
for f in $mid $hi; do echo $f > $P/scaling_max_freq; sleep 1; g=$(taskset -c $CPU ./build/memlat --freq | cut -d" " -f1)
  for ws in 16384 8388608; do for i in 1 2 3; do taskset -c $CPU ./build/memlat $ws --reps 1 --huge 1 | sed "s/^/capped,$f,$g,/" >> data/raw/pitfall_freq.csv; done; done; done
echo $orig > $P/scaling_max_freq; echo done
