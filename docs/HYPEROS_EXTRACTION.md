# 📦 HyperOS Application & Framework Extraction Guide

Complete instructions for extracting system applications, native shared libraries, and framework jars from stock Xiaomi HyperOS firmware for porting into OrangeUI Liquid Glass.

---

## 1. Preparing the Donor Firmware

Acquire an official Xiaomi HyperOS Fastboot ROM or Recovery ROM archive:
- **Fastboot ROM:** Contains `super.img` or `images/system.img`.
- **Recovery ROM:** Contains `payload.bin`, extractable using `payload-dumper-go`.

---

## 2. Step 1: Unpacking Partition Images

Unpack dynamic partition images using the OrangeUI CLI:
```bash
python3 cli/repack_super.py unpack --input /path/to/hyperos/super.img --output extracted/charoite
```
The utility automatically converts Android sparse images (`simg2img`), inspects liblp partition metadata (`lpdump`), and extracts active slot partitions (`system`, `product`, `system_ext`, `mi_ext`, `vendor`).

---

## 3. Step 2: Extracting Applications & Framework Components

Run the automated extractor:
```bash
python3 cli/extract_hyperos.py --system extracted/charoite/ --output inject/
```

### Key Extracted Components:
1. **HyperOS Launcher:**
   - Path: `/system/product/priv-app/MiuiHome/MiuiHome.apk`
   - Handles gesture navigation, fluid glass animations, and icon layouts.
2. **SystemUI & Control Center:**
   - Path: `/system/product/priv-app/MIUISystemUIPlugin/MIUISystemUIPlugin.apk`
   - Houses the signature Liquid Glass control center.
3. **Settings:**
   - Path: `/system/product/priv-app/MISettings/MISettings.apk`
4. **Theme Manager:**
   - Path: `/system/product/app/MIUIThemeManagerGlobal/MIUIThemeManagerGlobal.apk`
5. **Leica / Xiaomi Camera:**
   - Path: `/system/product/priv-app/MiuiCamera/MiuiCamera.apk`

---

## 4. Step 3: Extracting Xiaomi Core Frameworks

In modern HyperOS, Xiaomi places core framework modules inside `system_ext`:
- `miui-framework.jar` (Core MIUI/HyperOS APIs)
- `miui-services.jar` (Xiaomi system server extensions)
- `xiaomi-framework.jar`
- `miuix.jar` (Liquid Glass visual elements & widgets)
- `MiuiBooster.jar`
- `framework.jar`, `services.jar`, and `framework-res.apk`

The extractor automatically pulls these into `inject/framework/` and adds entries into `inject/manifest.json`.

---

## 5. Step 4: Validating the Injection Manifest

Verify all extracted files strictly:
```bash
python3 cli/manifest_parser.py --manifest inject/manifest.json --validate
```
