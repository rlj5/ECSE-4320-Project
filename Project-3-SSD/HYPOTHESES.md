# Pre-experiment hypotheses (Project 3, SSD performance profiling)

Device: WD PC SN740 512 GB (M.2 2230, NVMe, TLC, DRAM-less with Host Memory Buffer, dynamic pseudo-SLC cache), in a laptop with an AMD Ryzen 7 5825U.
Setup under test: **Windows-native fio.exe (windowsaio, unbuffered I/O) on an NTFS file on this SSD**, driven from WSL2. (WSL2's own disk is a virtual disk file; measuring inside it would not measure the SN740, see pitfall P4.) Every prediction has a reason and a "wrong if".

## 0. Facts these predictions rest on
| fact | value | source / how to check |
|---|---|---|
| Vendor claims (512 GB) | sequential read up to 5,000 MB/s, write up to 4,000 MB/s, random up to about 460k read / 800k write IOPS (reseller listing; "up to" figures at high queue depth) | scan.co.uk listing; check the WD datasheet |
| Architecture | TLC NAND (BiCS5), **DRAM-less**, 64 MB host memory buffer (HMB), dynamic SLC cache | drivesolutions.com listing ("HMB-SLC cache"); WD announcement coverage |
| SLC cache size | not published by me/verified: dynamic pseudo-SLC caches of this drive class commonly cover roughly a fifth to a third of capacity on a clean drive, so for 512 GB about **100 to 170 GB (a guess, not a datasheet value)**; it shrinks as the drive fills | general knowledge; **measure it (state test) and say whether it was observable** |
| Interface | PCIe 4.0 x4 drive; CrystalDiskInfo later reported a current **PCIe 3.0 x4** link and **PCIe 4.0 x4** supported mode. Gen3 x4 theoretical payload ceiling is approximately 3.94 GB/s before higher-level overhead. | CrystalDiskInfo Transfer Mode (current | supported) |
| Little's Law for a queue | in-flight requests = IOPS x latency; knee QD* about X_max x unloaded latency | derived |
| Windows I/O path | fio windowsaio + `--direct=1` uses unbuffered I/O (no file cache); NTFS sends TRIM when a file is deleted; the volume is likely the system drive (C:) | fio docs; `fsutil behavior query DisableDeleteNotify` |

## 1. Predictions (Windows, NTFS, windowsaio, direct I/O, incompressible data)
**H1. QD1 baselines.**
- 4 KiB random read: mean **70 to 130 us**, p99 within 2x of the mean (**90 to 250 us**), so 8k to 14k IOPS. (Host-memory-buffer mapping lookups and the Windows stack add to raw NAND read time.)
- 4 KiB random write: mean **20 to 60 us** (acknowledged from the controller's buffer/SLC), p99 under 150 us, so 15k to 45k IOPS; writes faster than reads at QD1.
- 128 KiB sequential read: **0.9 to 1.5 GB/s** (about 90 to 140 us: roughly 45 us transfer at 3 GB/s plus latency); 128 KiB sequential write: **1.0 to 2.0 GB/s**.
- *Wrong if:* 4K QD1 read is under 40 us (a cache above the device is serving it) or over 200 us.

**H2. Block-size sweep.**
- At QD32: 4 KiB random read **150k to 400k IOPS** (one fio job is host-limited below the vendor's 460k), throughput grows with block size and saturates near the interface limit (**about 3.0 to 3.5 GB/s if the link is Gen3, 4 to 5 GB/s if Gen4**) from 64 to 128 KiB upward. IOPS falls roughly as 1/bs past saturation.
- Random approaches sequential throughput (within 20%) from about 64 to 128 KiB.
- 4 KiB random write QD32 burst: **100k to 250k IOPS**; sequential 128 KiB write burst **2 to 3.5 GB/s**.
- *Wrong if:* sequential read saturates below 2 GB/s (host limit, encryption, or antivirus) or exceeds the link limit (impossible: indicates caching).

**H3. Read/write mix (4 KiB, QD32).** Total IOPS at 100% read is highest; 70/30 and 50/50 are **20% to 50% lower** than read-only (reads wait behind programs); read latency rises with write share (**+30% to +200%** at 50/50). Pure write may exceed 50/50 in burst because of the SLC buffer, but not at steady state.

**H4. Queue depth and Little's Law.**
- 4 KiB random read: IOPS grows about linearly to a knee at **QD 16 to 64**, then flattens (**200k to 400k**); mean latency is flat near its QD1 value until the knee and then grows about as QD / IOPS (QD256 about 0.6 to 1.3 ms).
- Little's Law prediction: knee QD* about X_max x QD1 latency (about 250k x 90 us = **20 to 40**).
- 128 KiB sequential read saturates at **QD 2 to 8** (the interface, not parallelism, is the limit); 4 KiB random write knee at **QD 8 to 32**.
- IOPS x mean latency equals QD up to measurement error at every QD (identity for a closed-loop generator): it is a **consistency check**, not a saturation test.
- *Wrong if:* IOPS still rises at QD256 (a deeper device queue than assumed) or flattens below QD4.

**H5. Tail latency.** At a mid QD (about 8) p99 is **1.5x to 3x** the mean and p99.9 **3x to 10x**; near the knee p99.9 is 5x to 15x the median and p99.99 above 1 ms for reads on a DRAM-less drive; random writes have heavier tails than reads at steady state (garbage collection, SLC folding). Windows scheduling adds a floor of tens of microseconds.

**H6. Device state and thermals.**
- Random 4 KiB writes on a fresh/TRIMmed file start at the burst rate and **fall by 30% to 60%** toward steady state after tens of GiB; the preconditioned run starts near the low rate.
- Sequential 1 MiB writes: about 3 GB/s while the SLC cache lasts, then **1.0 to 1.6 GB/s** (direct-to-TLC rate of a DRAM-less 512 GB drive); the cliff appears after roughly 100 to 170 GiB if the drive is mostly empty (**this may not be observable on a fairly full system drive; say so if not**).
- Temperature rises **10 to 25 C** during sustained writes; whether throttling starts (typically 70 to 80 C) depends on the chassis; I cannot predict it.

**H7. Misleading setups (predicted size of the error against the correct QD32 direct run).**
- P1 buffered I/O on a 1 GiB file already in the OS cache: **5x to 50x** higher IOPS than the same job with unbuffered I/O (cache hits); compare at equal QD1 (`buffered_sync_1GiB` vs `direct_sync_1GiB_same_file_control`).
- P2 `sync` engine with iodepth 32: behaves as **QD1** (7x to 20x lower IOPS than the QD32 run).
- P3 reading a file that was never written: **10x to 100x** inflated IOPS (zeros returned without touching the NAND).
- P4 running fio inside WSL2 on its ext4 disk (virtual disk on the host): results differ from native Windows by **at least 20%** in either direction (host caching, extra queueing); it measures the wrong layer.

**H8. Measurement quality.** Run-to-run coefficient of variation: reads 2% to 6%, random writes 5% to 15% (garbage collection), higher on a system drive with background activity; antivirus real-time scanning or BitLocker (software encryption) can lower small-block IOPS by 5% to 30%: record their state.

## 2. Things I expect might go wrong (so I recognise them, not hide them)
Throttling mid-run, the SLC cliff not reachable because the drive is nearly full, temperature unreadable without Administrator rights, Windows Update or Defender running during a test, a PCIe link at Gen3 making the "5 GB/s" claim unreachable, and too few repetitions for tails (p99.99 needs more than 10,000 I/Os per run: it has, at the default runtime, for all but the QD1 write tests).

## 3. Sources for section 0
- https://www.scan.co.uk/products/512gb-wd-pc-sn740-m2-2230-pcie-40-x4-nvme-ssd-5000mb-s-read-4000mb-s-write-460k-800k-iops-tcg-pyrite (rated speeds and IOPS as listed)
- https://drivesolutions.com/sddptqd-512g-wd-sn740-512gb-2230-nvme-ssd-122536.html (TLC, HMB, SLC cache)
- https://nascompares.com/news/western-digital-introduces-sn740-nvme-ssd/amp/ (announcement coverage)
- https://bsdio.com/fio/ and the fio manual (Windows builds, windowsaio, escaping the drive colon in `filename`)
