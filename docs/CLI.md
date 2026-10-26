# 🍊 OrangeUI CLI Reference Manual

Complete technical documentation for the OrangeUI Python Core (`cli/`).

## General Architecture & Conventions
- **Runtime:** Python 3.12+ (tested and verified on Python 3.12 through 3.15).
- **Fail-Fast Principle:** On any unhandled error, processes immediately halt, log full diagnostic information, and exit with status code `1`.
- **Unified Logging:** Formatted terminal logging via `rich` + automatic timestamped logging to `releases/logs/YYYY-MM-DD_HH-MM.log`.
- **Log Entry Standard:** `[YYYY-MM-DD HH:MM:SS] [LEVEL] [MODULE] Message`.
- **Relative Path Resolution:** All scripts automatically resolve paths relative to the repository root.

---

## 1. `cli/pipeline.py` (Unified Line Orchestrator & Maintenance)
The central orchestrator for end-to-end execution, workspace maintenance, and output archiving.

### 1.1. Line Mode (`--line`)
Executes the full pipeline from raw `super.img` to flashable release:
```bash
python3 cli/pipeline.py --line
python3 cli/pipeline.py --line --super /path/to/super.img --version 1.0
```
**Execution Chain:**
1. Unpacks `super.img` (`system`, `vendor`, `product`, `system_ext`, `mi_ext`).
2. Extracts HyperOS applications, 64-bit `.so` native libraries, and framework jars into `inject/`.
3. Validates the injection manifest and SELinux policies.
4. Injects OrangeUI assets and produces flashable release artifacts.

### 1.2. Cache Cleanup (`--clear`)
```bash
# Clean all temporary caches, unpacked trees, raw images, and release artifacts
python3 cli/pipeline.py --clear=all

# Clean only decompressed raw images (*_raw.img, super_unsparse.img)
python3 cli/pipeline.py --clear=raw

# Clean only generated output APKs and JARs in inject/ and releases/
python3 cli/pipeline.py --clear=out
```

### 1.3. Compaction & Archiving (`--compact-*`)
```bash
# GZIP compression (.tar.gz)
python3 cli/pipeline.py --compact-gzip=all
python3 cli/pipeline.py --compact-gzip=out

# XZ maximum preset-9 compression (.tar.xz)
python3 cli/pipeline.py --compact-xz=all
python3 cli/pipeline.py --compact-xz=out

# Uncompressed TAR archive (.tar)
python3 cli/pipeline.py --compact-tar=all
python3 cli/pipeline.py --compact-tar=out
```

---

## 2. `cli/repack_super.py` (Dynamic Partition Tool)
Unpacks and builds Android dynamic partition `super.img` based on `lpunpack` and `lpmake`.

### 2.1. Unpack Action
```bash
python3 cli/repack_super.py unpack --input super.img --output extracted/charoite
```
**Options:**
- `--input, -i` *(required)*: Path to input `super.img` (both raw and sparse images are supported).
- `--output, -o`: Directory to save extracted partition images (default: `extracted/super`).
- `--partitions, -p`: List of target partitions to extract (default: `system vendor product system_ext mi_ext`).
- `--all, -a`: Extract all partitions found in super metadata.
- `--slot, -s`: Metadata slot index (default: `0`).

### 2.2. Repack Action
```bash
python3 cli/repack_super.py repack --input extracted/charoite --output releases/super.img
```
**Options:**
- `--input, -i` *(required)*: Directory containing partition `.img` files and `.repack_meta.json`.
- `--output, -o`: Path to output `super.img` (default: `releases/super.img`).
- `--device-size, -d`: Exact block device size in bytes (calculated automatically if omitted).
- `--no-sparse`: Output raw uncompressed super image instead of fastboot-flashable sparse image.
- `--disable-verity`: Mark dm-verity disabled in metadata.

---

## 3. `cli/extract_hyperos.py` (HyperOS App & Framework Extractor)
Extracts system APKs, 64-bit `.so` native libraries, and framework jars from donor partitions.

### Usage
```bash
# Extract from a directory of unpacked partition images:
python3 cli/extract_hyperos.py --system extracted/charoite/ --output inject/

# Extract specific applications:
python3 cli/extract_hyperos.py --system extracted/charoite/ --output inject/ --targets MiuiHome Settings MiuiSystemUI
```
**Options:**
- `--system, -s` *(required)*: Path to partition `.img` file or directory containing partition images.
- `--output, -o`: Target folder for extracted assets (default: `inject/`).
- `--targets, -t`: List of target application names to filter.
- `--all, -a`: Extract all discovered APKs.
- `--no-libs`: Skip searching and copying `.so` native libraries.
- `--no-framework`: Skip searching and copying framework `.jar` components.

---

## 4. `cli/patch_framework.py` (Smali & Bytecode Patcher)
Patches `services.jar`, `framework.jar`, or disassembled `.smali` trees.

### 4.1. Directory Mode (`dir`)
```bash
python3 cli/patch_framework.py dir --path extracted/smali
```
- Disables signature verification checks in `PackageManagerService.smali` (`compareSignatures`, `checkSignatures`).
- Neutralizes `ro.miui.*` and `ro.hyperos.*` build property checks.

### 4.2. JAR Mode (`jar`)
```bash
python3 cli/patch_framework.py jar --input services.jar --output releases/services_patched.jar
```

### 4.3. Stub Generator (`stub`)
```bash
python3 cli/patch_framework.py stub --class-name com.miui.internal.util.DeviceHelper --output inject/smali/DeviceHelper.smali
```
Generates valid Smali stub classes returning safe default values (`false`, `0`, `null`, `void`).

---

## 5. `cli/inject_apks.py` (Asset Injector & OTA Builder)
Injects files from `inject/` into target system directory or raw `system.img`.

### Usage
```bash
# Inject into unpacked filesystem directory:
python3 cli/inject_apks.py --target extracted/super/system --inject inject/

# Inject directly into EXT4 system.img:
python3 cli/inject_apks.py --target system.img --output releases/system_injected.img --inject inject/

# Generate flashable OTA update ZIP:
python3 cli/inject_apks.py --inject inject/ --ota-zip releases/OrangeUI_Update_v1.0.zip
```

---

## 6. `cli/build_gsi.py` (Automated GSI Builder)
Downloads remote Generic System Images (`.img.xz`), decompresses them, injects OrangeUI Liquid Glass assets, and repacks.

```bash
python3 cli/build_gsi.py --url https://github.com/.../LineageOS-23.2_GSI.img.xz --inject inject/ --output releases/OrangeUI-GSI.img
```

---

## 7. `cli/charoite_builder.py` (Redmi Note 15 Pro 4G Builder)
Platform-specific builder for the MT6789 (Helio G99) platform. Pulls Lights HAL, PHH brightness calibration (`persist.sys.phh.backlight.scale=0`), NDK libraries, and Treble overlays from `Fabric/payload`.

```bash
python3 cli/charoite_builder.py --output releases/charoite --version 1.0
```

---

## 8. `cli/manifest_parser.py` (Manifest Validator & Generator)
```bash
# Display formatted manifest table:
python3 cli/manifest_parser.py --manifest inject/manifest.json --show

# Validate strictly that all source files exist on disk:
python3 cli/manifest_parser.py --manifest inject/manifest.json --validate

# Automatically generate manifest.json from directory:
python3 cli/manifest_parser.py --generate inject/
```
