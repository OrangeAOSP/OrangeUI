# 🍊 OrangeUI: Liquid Glass ROM Customization Toolkit

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/python-3.12+-orange.svg)](cli/)
[![Rust: Ratatui](https://img.shields.io/badge/rust-ratatui%20%2B%20crossterm-red.svg)](tui/)
[![Architecture: Liquid Glass](https://img.shields.io/badge/UI-Liquid%20Glass%20(No%20Monet)-brightgreen.svg)]()

**OrangeUI** — открытый инструментарий и среда модификации системных Android-образов (`super.img`, GSI, `system.img`).
Проект позволяет извлекать фирменные системные приложения (включая рабочий стол, шторку и центр управления) из стоковых прошивок **HyperOS**, патчить их для нативной работы на чистом **AOSP / LineageOS / Treble GSI**, а также пересобирать динамические разделы `super.img` с внедрением эстетики **OrangeUI Liquid Glass** (чистое стекло, эффекты размытия, без динамических палитр Material You).

---

## 🏛️ Архитектура проекта

Проект разделен на два независимых слоя:

```
┌─────────────────────────────────────────────────────────────┐
│                 OrangeUI TUI (Rust)                         │
│  Интерактивная оболочка (ratatui + crossterm)                │
│  Меню операций, статус-бар, неблокирующий live-лог          │
└──────────────────────────────┬──────────────────────────────┘
                               │ вызовы subprocess
┌──────────────────────────────▼──────────────────────────────┐
│                 OrangeUI Core CLI (Python 3.12+)            │
│  repack_super  •  extract_hyperos  •  inject_apks           │
│  patch_framework  •  build_gsi  •  manifest_parser          │
│  Цветной логгер (rich) + автозапись в releases/logs/         │
└─────────────────────────────────────────────────────────────┘
```

### 📂 Структура репозитория

```text
OrangeUI/
├── cli/                          # Python-ядро (вся тяжелая работа)
│   ├── repack_super.py           # Распаковка и сборка super.img (lpunpack / lpmake)
│   ├── patch_framework.py        # Smali-патчинг framework.jar / services.jar
│   ├── inject_apks.py            # Инъекция APK, lib64, props, sepolicy в system
│   ├── extract_hyperos.py        # Извлечение приложений и lib64 из донора HyperOS
│   ├── build_gsi.py              # Загрузка .xz GSI, распаковка, инъекция и репак
│   ├── charoite_builder.py       # Релизный билдер для Redmi Note 15 Pro 4G
│   ├── manifest_parser.py        # Валидация и автогенерация manifest.json
│   └── utils/                    # Логгер (rich), проверка зависимостей, FS утилиты
├── tui/                          # Графический терминальный интерфейс (Rust)
│   ├── Cargo.toml
│   └── src/main.rs               # Меню, перехват stdout/stderr, горячие клавиши
├── inject/                       # Каталог входных данных (APK, lib64, manifest.json)
│   ├── manifest.json
│   ├── build.prop.patch
│   └── sepolicy.rule
├── releases/                     # Выходные файлы (super.img, GSI, ZIP, логи)
│   └── logs/                     # Логи (формат: YYYY-MM-DD_HH-MM.log)
├── docs/                         # Подробная документация
│   ├── CLI.md                    # Справочник по аргументам CLI-скриптов
│   ├── TUI.md                    # Руководство по TUI-интерфейсу
│   ├── HYPEROS_EXTRACTION.md     # Инструкция по портированию из HyperOS
│   └── SMALI_PATCHING.md         # Руководство по Smali-патчингу
├── LICENSE                       # GNU General Public License v3
└── README.md
```

---

## 🌿 Ветки Git

- **`master` (Универсальная):** работает с `super.img` любого Android-устройства (динамические разделы Qualcomm, Exynos, Unisoc и др.). **Любые вендорные фиксы MediaTek здесь строго запрещены.**
- **`xiaomi-charoite` (Специфичная):** ориентирована на смартфон **Redmi Note 15 Pro 4G** (платформа MediaTek MT6789 Helio G99). Содержит Lights HAL, калибровку подсветки (`persist.sys.phh.backlight.scale=0`), NDK-библиотеки и Treble-оверлеи из `Fabric/payload`.

---

## ⚡ Быстрый старт

### 1. Требования к системе
- Linux (Ubuntu 22.04+, Arch Linux, Omarchy, Debian 12+)
- Python 3.12+ с установленной библиотекой `rich`
- Rust 1.80+ и `cargo` (для сборки TUI)
- Системный toolchain: `lpunpack`, `lpmake`, `simg2img`, `img2simg`, `e2fsdroid`, `mke2fs`, `debugfs`, `xz`, `unzip`

Проверить доступность утилит:
```bash
python3 cli/utils/deps.py
```

### 2. Сборка TUI
```bash
cd tui
cargo build --release
cd ..
```

### 3. Запуск TUI
```bash
./tui/target/release/orangeui-tui
```

---

## 🚀 Основные сценарии CLI

### Сценарий А: Распаковка и обратная сборка `super.img`
```bash
# 1. Распаковать только system, vendor, product:
python3 cli/repack_super.py unpack --input super.img --output extracted/super

# 2. Модифицировать разделы или внедрить файлы из inject/:
python3 cli/inject_apks.py --target extracted/super --inject inject/

# 3. Собрать новый flashable super.img:
python3 cli/repack_super.py repack --input extracted/super --output releases/super.img
```

### Сценарий Б: Извлечение приложений из HyperOS
```bash
python3 cli/extract_hyperos.py \
  --system /path/to/hyperos/system.img \
  --output inject/ \
  --targets MiuiHome Settings MiuiSystemUI
```
Скрипт автоматически проанализирует зависимости в DEX, скопирует нужные `.so` из `system/lib64/` и сгенерирует `inject/manifest.json`.

### Сценарий В: Автоматическая сборка GSI
```bash
python3 cli/build_gsi.py \
  --url https://github.com/Doze-off/lineage_treble/releases/download/.../LineageOS-23.2_GSI.img.xz \
  --inject inject/ \
  --output releases/OrangeUI-GSI.img
```

### Сценарий Г: Сборка релиза для Xiaomi Charoite (MT6789)
```bash
python3 cli/charoite_builder.py --output releases/charoite --version 1.0
```
Результат сборки: `releases/charoite/OrangeUI-charoite-v1.0.zip` (содержит образы и скрипты быстрой прошивки `flash.sh` / `flash.bat`).

---

## 📜 Формат `manifest.json`

Файл `inject/manifest.json` задает отображение файлов из папки `inject/` в пути внутри результирующей системы:

```json
{
  "OrangeUI_Settings.apk": "/system/priv-app/Settings/Settings.apk",
  "OrangeUI_Launcher.apk": "/system/priv-app/Launcher3/Launcher3.apk",
  "OrangeUI_SystemUI.apk": "/system/priv-app/SystemUI/SystemUI.apk",
  "lib64/libfoo.so": "/system/lib64/libfoo.so"
}
```

Проверить валидность манифеста:
```bash
python3 cli/manifest_parser.py --manifest inject/manifest.json --show
```

---

## 📄 Лицензия

Проект распространяется под свободной лицензией **GNU General Public License v3 (GPL v3)**. Подробности см. в файле [LICENSE](LICENSE).
