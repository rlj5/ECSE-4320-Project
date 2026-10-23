#!/usr/bin/env bash
# Checks Project 2 measurements. Writes env/preflight.txt. First run this before run_all.sh.
cd "$(dirname "$0")"; mkdir -p env; o=env/preflight.txt; : > $o
say(){ echo "$@" | tee -a $o; }
say "== preflight $(date -Is)"
if grep -qi microsoft /proc/version; then say "WSL2: YES  -> memory/TLB behaviour is nested-virtualized; hardware perf counters and cpufreq are usually unavailable. State this in the report."; else say "WSL2: no (native Linux)"; fi
say "logical CPUs: $(nproc)   physical cores: $(lscpu -p=CORE | grep -v '^#' | sort -u | wc -l)   SMT active: $(cat /sys/devices/system/cpu/smt/active 2>/dev/null)"
say "MemAvailable: $(awk '/MemAvailable/{printf "%.1f GiB", $2/1048576}' /proc/meminfo)  (full run allocates about 2.5 GiB; below 3.5 GiB the driver halves its buffers)"
say "THP mode: $(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null)  (needs madvise or always for the huge-page runs; check thp_kb > 0 in data/raw/tlb.csv)"
if command -v perf >/dev/null; then
  if perf stat -x, -e cycles -- true 2>&1 | grep -qE '^[0-9]+,'; then say "perf hardware counters: WORK"; else say "perf hardware counters: NOT usable (installed but 'not supported'): cache/TLB counter correlation will fall back to the AMAT model; say so in the report"; fi
else say "perf: not installed (sudo apt install linux-tools-generic). In WSL2 hardware counters are usually unsupported anyway."; fi
say "cpufreq governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'not exposed')"
say "AC power online: $(cat /sys/class/power_supply/A*/online 2>/dev/null | tr '\n' ' ')"
say "load average now: $(cut -d' ' -f1-3 /proc/loadavg)  (should be < 0.5; close browsers, Docker Desktop, etc.)"
say "physical-core CPU list used by the driver (first logical CPU of each core): $(lscpu -p=CPU,CORE | grep -v '^#' | awk -F, '!s[$2]++{printf "%s,", $1}')"
say "Windows side (do by hand, then write it in the report): power mode, Energy Saver on/off, RAM type/speed/channels (PowerShell: Get-CimInstance Win32_PhysicalMemory | ft Speed,ConfiguredClockSpeed,Manufacturer,Capacity)"
