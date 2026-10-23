#!/usr/bin/env bash
# Records the measurement environment required by the rubric -> env/<tag>_env.txt  (run as normal user; some lines need sudo for more detail)
set -uo pipefail; cd "$(dirname "$0")"; mkdir -p env; tag=${1:-all}; o=env/${tag}_env.txt
{ echo "### date"; date -Is; echo "### uname"; uname -a; echo "### os-release"; cat /etc/os-release 2>/dev/null | head -4
  echo "### lscpu"; lscpu; echo "### SMT active (1=on)"; cat /sys/devices/system/cpu/smt/active 2>/dev/null
  echo "### governor cpu0 / available"; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver 2>/dev/null
  echo "### freq min/max/cur (kHz) cpu0"; cat /sys/devices/system/cpu/cpu0/cpufreq/{cpuinfo_min_freq,cpuinfo_max_freq,scaling_cur_freq} 2>/dev/null
  echo "### boost (1=on)"; cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
  echo "### power"; cat /sys/class/power_supply/AC*/online /sys/class/power_supply/ADP*/online 2>/dev/null
  echo "### cpu topology (CPU,CORE,SOCKET)"; lscpu -p=CPU,CORE,SOCKET 2>/dev/null | grep -v '^#' | tr '\n' ' '; echo
  echo "### memory"; free -h; (sudo -n dmidecode -t memory 2>/dev/null | grep -E "Type:|Speed:|Size:|Configured" | sort | uniq -c) || echo "(dmidecode needs sudo: run 'sudo dmidecode -t memory' manually)"
  echo "### THP"; cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null; grep -i huge /proc/meminfo
  echo "### compiler"; gcc --version | head -1; echo "### python"; python3 --version; python3 -c "import pandas,matplotlib,numpy;print('pandas',pandas.__version__,'matplotlib',matplotlib.__version__,'numpy',numpy.__version__)"
  echo "### perf"; perf --version 2>&1 | head -1; echo "### perf_event_paranoid"; cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null
  echo "### fio"; fio --version 2>&1 | head -1
  echo "### block devices"; lsblk -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINTS 2>/dev/null
  echo "### nvme"; (nvme list 2>/dev/null || echo "(nvme-cli not installed / needs sudo)"); (sudo -n nvme id-ctrl /dev/nvme0 2>/dev/null | grep -E "^(mn|fr|sn)" | grep -v '^sn') || true
  echo "### nvme link"; cat /sys/class/nvme/nvme0/device/current_link_speed /sys/class/nvme/nvme0/device/current_link_width 2>/dev/null
  echo "### nvme io scheduler / queue"; cat /sys/block/nvme0n1/queue/scheduler /sys/block/nvme0n1/queue/nr_requests 2>/dev/null
  echo "### nvme temp (hwmon)"; for f in /sys/class/nvme/nvme0/hwmon*/temp1_input; do cat $f 2>/dev/null; done
  echo "### smart (sudo)"; (sudo -n smartctl -a /dev/nvme0 2>/dev/null | head -40) || echo "(run: sudo smartctl -a /dev/nvme0)"
} > $o 2>&1; echo "wrote $o"
