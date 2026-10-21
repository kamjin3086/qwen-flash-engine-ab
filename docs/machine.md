# The machine

Captured on the host after the run, 2026-10-21. Serial numbers, UUIDs, asset tags and MAC
addresses are removed; the rest is what the firmware and the OS report, unfiltered.

AZW is the DMI vendor string, `GTR Pro` the product string; the machine is sold as the
Beelink GTR9 Pro.

| | |
|---|---|
| System | AZW GTR Pro (Beelink GTR9 Pro), BIOS AMI `GTRPR05`, released 2025-12-25, platform firmware 5.36 |
| CPU | AMD Ryzen AI Max+ 395, 16 cores / 32 threads, 625–5187 MHz, 768 KiB L1d, 16 MiB L2, 64 MiB L3 |
| Memory | 8 × 16 GiB Micron LPDDR5-8000 (`MT62F4G32D8DV-023 WT`), one per channel (P0 A–H), 8000 MT/s configured |
| Memory bandwidth | 256-bit at 8000 MT/s, so 256 GB/s peak by arithmetic. Not measured; no bandwidth benchmark was run |
| GPU | Radeon 8060S, PCI `1002:1586` rev c1, gfx1151, unified memory, no dedicated VRAM. The compute-unit count is not exposed by sysfs, and `rocminfo` is not installed on the host (it lives inside the engine image), so neither is quoted here |
| OS | Fedora 44, kernel `7.2.9-201.fc44.x86_64` |
| CPU power | `amd_pstate` active, governor `powersave`; the box exposes no vendor power-profile interface |
| Storage | one 1.8 TB SSD, one 8 GiB zram device |
| Engine userspace | ROCm/HIP 7.13.60980, as reported by the Kyojin image's own startup log |

Memory is soldered and it is the same pool the GPU uses through GTT. That is the fact behind
the container findings: an 89 GB pack, a 30 GiB lookup table and a 262144-position KV pool are
all competing for the one 124 GiB the kernel reports as available.

## Raw excerpts

`lscpu`, selected lines:

    Model name:   AMD RYZEN AI MAX+ 395 w/ Radeon 8060S
    CPU(s):       32
    Core(s):      16 per socket, 1 socket, 2 threads per core
    CPU max MHz:  5187.5000
    CPU min MHz:  625.0000
    L1d cache:    768 KiB (16 instances)
    L1i cache:    512 KiB (16 instances)
    L2 cache:     16 MiB (16 instances)
    L3 cache:     64 MiB (2 instances)
    Virtualization: AMD-V

`dmidecode -t memory`, one of eight identical entries, and the channel list:

    Size: 16 GiB
    Form Factor: Other
    Locator: DIMM 0
    Bank Locator: P0 CHANNEL A
    Type: LPDDR5
    Speed: 8000 MT/s
    Manufacturer: Micron Technology
    Part Number: MT62F4G32D8DV-023 WT
    Rank: 2
    Configured Memory Speed: 8000 MT/s
    Volatile Size: 16 GiB

    Bank Locator: P0 CHANNEL A ... P0 CHANNEL H   (eight channels)

`dmidecode -t bios`:

    Vendor: American Megatrends International, LLC.
    Version: GTRPR05
    Release Date: 12/25/2025
    Platform Firmware Revision: 5.36

`lspci -nn`:

    c7:00.0 Display controller [0380]: Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo
    [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] [1002:1586] (rev c1)

`/proc/meminfo` and power state:

    MemTotal:       130999796 kB          (124.9 GiB)
    scaling_governor: powersave
    /sys/devices/system/cpu/amd_pstate/status: active
