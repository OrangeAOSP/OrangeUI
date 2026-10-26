<p align="center">
  <img src="assets/afterglow.svg" width="160" height="160" alt="OrangeUI Afterglow Logo">
</p>

<h1 align="center">🍊 OrangeUI: Afterglow Edition</h1>

<p align="center">
  <strong>Liquid Glass Android Customization & Firmware Modification Toolkit</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License: GPL v3"></a>
  <a href="cli/"><img src="https://img.shields.io/badge/python-3.12+-orange.svg" alt="Python 3.12+"></a>
  <a href="tui/"><img src="https://img.shields.io/badge/rust-ratatui%200.30%20%2B%20crossterm-red.svg" alt="Rust Ratatui"></a>
  <img src="https://img.shields.io/badge/Release-Afterglow-brightgreen.svg" alt="Release: Afterglow">
  <img src="https://img.shields.io/badge/Style-Liquid%20Glass%20(No%20Monet)-blueviolet.svg" alt="Style: Liquid Glass">
</p>

---

## 📖 Overview

**OrangeUI (Afterglow Edition)** is an open-source customization suite and firmware modification toolkit for Android images (`super.img`, Treble GSI, `system.img`).
The project enables developers to extract proprietary system applications (including launchers, control centers, and camera apps) and framework components from stock **HyperOS** donor builds, patch bytecode dependencies for native execution on clean **AOSP / LineageOS / Treble GSI** bases, and repack dynamic `super.img` partitions with the **OrangeUI Liquid Glass** design aesthetic (pure frosted glass, blur shaders, no Monet dynamic tinting).

---

## 🏛️ System Architecture

OrangeUI consists of two independent, decoupled layers:

```
┌─────────────────────────────────────────────────────────────┐
│                 OrangeUI TUI (Rust)                         │
│  Interactive Terminal UI (ratatui 0.30 + crossterm 0.29)    │
│  Operations menu, live process stream, non-blocking events  │
└──────────────────────────────┬──────────────────────────────┘
                               │ subprocess invocation
┌──────────────────────────────▼──────────────────────────────┐
│                 OrangeUI Core CLI (Python 3.12+)            │
│  pipeline  •  repack_super  •  extract_hyperos              │
│  inject_apks  •  patch_framework  •  build_gsi              │
│  Rich terminal logging + persistent logs in releases/logs/  │
└─────────────────────────────────────────────────────────────┘
```

### 📂 Repository Tree

```text
OrangeUI/
├── assets/                       # Visual assets
│   └── icon.svg                  # Official OrangeUI Vector Icon
├── cli/                          # Python 3.12+ Core Engine
│   ├── pipeline.py               # Unified Line mode, cleanup, and compactor
│   ├── repack_super.py           # Unpack and build super.img (lpunpack / lpmake)
│   ├── extract_hyperos.py        # Extract APKs, 64-bit .so libs, and framework jars
│   ├── patch_framework.py        # Smali PMS signature bypass & stub generator
│   ├── inject_apks.py            # Injects assets, build.prop.patch, and sepolicy
│   ├── build_gsi.py              # Download GSI (.xz), decompress, inject, and repack
│   ├── charoite_builder.py       # Dedicated release builder for Redmi Note 15 Pro 4G
│   ├── manifest_parser.py        # Validates and generates manifest.json
│   └── utils/                    # Logger (rich), dependency checker, FS tools
├── tui/                          # Rust Terminal User Interface
│   ├── Cargo.toml
│   └── src/main.rs               # Menu, async process piping, keybindings
├── inject/                       # Injection workspace (APKs, lib64, framework jars)
│   ├── manifest.json
│   ├── build.prop.patch
│   └── sepolicy.rule
├── releases/                     # Output artifacts (super.img, GSI, ZIP, logs)
│   ├── compact/                  # Compressed archives (.tar.gz, .tar.xz, .tar)
│   └── logs/                     # Timestamped logs (YYYY-MM-DD_HH-MM.log)
├── docs/                         # Detailed Technical Documentation
│   ├── CLI.md                    # CLI reference and argument manual
│   ├── TUI.md                    # TUI hotkey and operational guide
│   ├── HYPEROS_EXTRACTION.md     # HyperOS extraction walkthrough
│   └── SMALI_PATCHING.md         # Framework smali patching manual
├── tests/                        # Automated unit and integration test suite
├── LICENSE                       # GNU General Public License v3
└── README.md
```

---

## 🌿 Git Branches

- **`master` (Universal):** Works with standard `super.img` images across any device (Qualcomm, Exynos, Unisoc, Tensor). **MediaTek vendor-specific fixes are strictly forbidden on this branch.**
- **`xiaomi-charoite` (Device-Specific):** Dedicated to the **Redmi Note 15 Pro 4G** (MediaTek MT6789 Helio G99 platform). Integrates Lights HAL, brightness calibration (`persist.sys.phh.backlight.scale=0`), NDK libraries, and Treble overlays from `Fabric/payload`.

---

## ⚡ Quick Start

### 1. Requirements
- Linux (Arch Linux, Ubuntu 22.04+, Debian 12+, Fedora)
- Python 3.12+ with the `rich` library installed
- Rust 1.80+ and Cargo (for TUI compilation)
- Android host toolchain: `lpunpack`, `lpmake`, `simg2img`, `img2simg`, `e2fsdroid`, `mke2fs`, `debugfs`, `xz`, `unzip`, `fsck.erofs`

Verify installed host utilities:
```bash
python3 cli/utils/deps.py
```

### 2. Compile TUI
```bash
cd tui
cargo build --release
cd ..
```

### 3. Launch TUI
```bash
./tui/target/release/orangeui-tui
```

---

## 🚀 CLI Commands & New Operational Flags

### 1. One-Shot Line Execution (`--line`)
Executes the entire ROM modification chain seamlessly from start to finish:
```bash
python3 cli/pipeline.py --line
# or via compiled TUI binary:
./tui/target/release/orangeui-tui --line
```

### 2. Workspace & Cache Cleaning (`--clear`)
```bash
# Clean all temporary caches, unpacked trees, raw images, and release artifacts:
python3 cli/pipeline.py --clear=all

# Clean only decompressed raw images (*_raw.img, super_unsparse.img):
python3 cli/pipeline.py --clear=raw

# Clean only extracted output APKs and JARs:
python3 cli/pipeline.py --clear=out
```

### 3. Output Archiving & Compaction (`--compact-*`)
```bash
# Package into .tar.gz (GZIP):
python3 cli/pipeline.py --compact-gzip=out     # Output APKs, JARs, and libs
python3 cli/pipeline.py --compact-gzip=all     # All workspace deliverables

# Package into .tar.xz (Maximum Preset 9 XZ Compression):
python3 cli/pipeline.py --compact-xz=out
python3 cli/pipeline.py --compact-xz=all

# Package into uncompressed .tar:
python3 cli/pipeline.py --compact-tar=all
python3 cli/pipeline.py --compact-tar=out
```

---

## 🛠️ Individual CLI Workflows

### Scenario A: Unpack and Repack `super.img`
```bash
# 1. Unpack system, vendor, product, system_ext, mi_ext partitions:
python3 cli/repack_super.py unpack --input super.img --output extracted/charoite

# 2. Inject customized assets from inject/:
python3 cli/inject_apks.py --target extracted/charoite --inject inject/

# 3. Build flashable super.img:
python3 cli/repack_super.py repack --input extracted/charoite --output releases/super.img
```

### Scenario B: Extract HyperOS Applications & Frameworks
```bash
python3 cli/extract_hyperos.py --system extracted/charoite/ --output inject/
```
Automatically scans DEX bytecodes, copies 64-bit `.so` native libraries into `inject/lib64/`, extracts core Xiaomi framework JARs into `inject/framework/`, and generates `inject/manifest.json`.

---

## 📋 The `POST` Stage: What to Do After Getting the Results

Once OrangeUI completes building your release artifacts, follow this post-processing and installation checklist:

### 1. Verification of Output Artifacts
Inspect the generated files inside `releases/` (or `releases/charoite/`):
- `super.img` — Flashable Android dynamic partition image containing your injected partitions.
- `system.img` — Modified Generic System Image with Liquid Glass assets.
- `OrangeUI-charoite-v1.0.zip` — Fastboot flashable distribution archive with automated scripts.

Verify manifest integrity:
```bash
python3 cli/manifest_parser.py --manifest inject/manifest.json --validate
```

### 2. Flashing via Fastboot (FastbootD Mode)
Dynamic partitions (`super.img`) must be flashed from **FastbootD** mode (userspace fastboot):

1. Reboot your device into bootloader mode:
   ```bash
   adb reboot bootloader
   ```
2. Enter FastbootD mode:
   ```bash
   fastboot reboot fastboot
   ```
3. Flash the generated dynamic super partition:
   ```bash
   fastboot flash super releases/super.img
   ```
4. Wipe userdata for a clean first boot:
   ```bash
   fastboot -w
   ```
5. Reboot into system:
   ```bash
   fastboot reboot
   ```

### 3. Flashing via Automated Charoite Package
For Redmi Note 15 Pro 4G (`charoite`):
1. Extract `releases/charoite/OrangeUI-charoite-v1.0.zip`.
2. Connect device in Fastboot mode.
3. Run the automated script:
   - **Linux:** `chmod +x flash.sh && ./flash.sh`
   - **Windows:** Double-click `flash.bat`

### 4. Post-Boot Verification & Configuration
After the first boot:
1. **SELinux State:** Verify whether permissions are correctly enforced:
   ```bash
   adb shell getenforce
   ```
2. **Signature Spoofing:** Ensure PackageManagerService allows the injected applications without security warnings:
   ```bash
   adb shell pm list packages | grep -E "miui|xiaomi"
   ```
3. **Logcat Monitoring:** Check logcat for any missing IPC services or stub requirements:
   ```bash
   adb logcat -s MiuiHome:V AndroidRuntime:E
   ```

---

## 📄 License

OrangeUI is distributed under the terms of the **GNU General Public License v3 (GPL v3)**. See [LICENSE](LICENSE) for full details.
