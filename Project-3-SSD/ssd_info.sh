#!/usr/bin/env bash
# Records SSD / Windows facts the report needs -> env/ssd_info.txt. Works from WSL2 through powershell.exe (interop). Anything that needs
# Administrator rights is skipped with a note: run from an elevated Windows Terminal to get it (temperature, BitLocker, Defender settings).
cd "$(dirname "$0")"; mkdir -p env; o=env/ssd_info.txt; : > $o
ps(){ echo "### $1" >> $o; powershell.exe -NoProfile -Command "$2" 2>&1 | tr -d '\r' >> $o || echo "(failed)" >> $o; echo >> $o; }
echo "### date: $(date -Is)   kernel: $(uname -r)" >> $o
ps "physical disks"        "Get-PhysicalDisk | Format-List FriendlyName,Model,MediaType,BusType,Size,HealthStatus,OperationalStatus,FirmwareVersion"
ps "reliability counters (temperature, wear, power-on hours; may need admin)" "Get-PhysicalDisk | Get-StorageReliabilityCounter | Format-List *"
ps "volumes"               "Get-Volume | Format-Table DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining -AutoSize"
ps "active power plan"     "powercfg /getactivescheme"
ps "TRIM (DisableDeleteNotify=0 means TRIM is ON)" "fsutil behavior query DisableDeleteNotify"
ps "BitLocker (needs admin)" "manage-bde -status C:"
ps "Defender real-time monitoring / exclusions (may need admin)" "Get-MpPreference | Format-List DisableRealtimeMonitoring,ExclusionPath"
ps "NVMe controllers"      "Get-PnpDevice -Class SCSIAdapter | Format-Table FriendlyName,Status -AutoSize"
echo "### fio.exe: $(fio.exe --version 2>/dev/null | tr -d '\r' || echo 'not on PATH (pass --fio to run_fio.py)')" >> $o
cat >> $o <<'NOTE'

### TO RECORD BY HAND (cannot be read reliably from here)
- PCIe link of the SSD (CrystalDiskInfo "Transfer Mode", or HWiNFO64 "PCIe link speed"): Gen3 x4 or Gen4 x4?  (decides the sequential ceiling)
- Windows power mode (Settings > System > Power), Energy Saver on/off, AC power connected
- Device Manager > Disk drives > the SSD > Policies: "Enable write caching on the device" and "Turn off Windows write-cache buffer flushing"
- Free space on the volume and the size of the test files
NOTE
echo "wrote $o"
