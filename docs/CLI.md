# 🍊 OrangeUI CLI Reference Manual

Документация по Python-ядру OrangeUI (`cli/`).

## Общие соглашения
- **Интерпретатор:** Python 3.12+ (поддерживается Python 3.12, 3.13, 3.14, 3.15).
- **Принцип Fail-Fast:** при любой ошибке процесс немедленно завершается с кодом `1`, записывая детальный трейсбек и причину в лог.
- **Логирование:** цветной интерактивный терминальный вывод через библиотеку `rich` + автоматическое ведение логов в файлах `releases/logs/YYYY-MM-DD_HH-MM.log`.
- **Формат логов:** `[YYYY-MM-DD HH:MM:SS] [LEVEL] [MODULE] Сообщение`.
- Все пути относительны к корню репозитория, файлы исполняемые (`chmod +x`).

---

## 1. `cli/repack_super.py`
Утилита для распаковки и сборки динамического раздела `super.img` (Android Dynamic Partitions) на основе `lpunpack` и `lpmake`.

### 1.1. Распаковка (`unpack`)
```bash
python3 cli/repack_super.py unpack --input super.img --output extracted/super
```
**Параметры:**
- `--input, -i` *(обязательный)*: Путь к исходному `super.img` (поддерживаются как raw, так и sparse-образы).
- `--output, -o`: Каталог для сохранения извлеченных разделов (по умолчанию `extracted/super`).
- `--partitions, -p`: Список разделов для извлечения (по умолчанию: `system vendor product`).
- `--all, -a`: Извлечь абсолютно все разделы, находящиеся в метаданных `super.img`.
- `--slot, -s`: Номер слота метаданных (по умолчанию `0`).

**Особенности:**
- Автоматически проверяет заголовок на Android Sparse (`0xED26FF3A`) и при необходимости разворачивает образ через `simg2img`.
- Определяет файловую систему каждого раздела (EXT4 / EROFS / F2FS) по суперблокам и сохраняет топологию в `.repack_meta.json`.

### 1.2. Сборка (`repack`)
```bash
python3 cli/repack_super.py repack --input extracted/super --output releases/super.img
```
**Параметры:**
- `--input, -i` *(обязательный)*: Каталог с образами разделов (`system.img`, `vendor.img`, `product.img`) и файлом `.repack_meta.json`.
- `--output, -o`: Путь к создаваемому `super.img` (по умолчанию `releases/super.img`).
- `--device-size, -d`: Точный размер целевого блочного устройства в байтах (если не указан, берется из метаданных или рассчитывается с запасом 5%).
- `--no-sparse`: Сгенерировать raw-образ вместо сжатого sparse-образа для fastboot.
- `--disable-verity`: Отключить проверку целостности dm-verity.

---

## 2. `cli/extract_hyperos.py`
Утилита извлечения системных приложений (лаунчер, настройки, SystemUI) и необходимых 64-битных `.so` библиотек из прошивки-донора HyperOS.

### Использование
```bash
python3 cli/extract_hyperos.py --system system.img --output inject/
```
**Параметры:**
- `--system, -s` *(обязательный)*: Путь к донорскому `system.img` (EXT4/EROFS) или к уже распакованному каталогу с деревом файлов системы.
- `--output, -o`: Целевая папка для сохранения APK и библиотек (по умолчанию `inject/`).
- `--targets, -t`: Имена конкретных приложений для извлечения (например: `MiuiHome Settings MiuiSystemUI`).
- `--all, -a`: Извлечь все обнаруженные APK из `/system/priv-app/` и `/system/app/`.
- `--no-libs`: Не искать и не копировать зависимые библиотеки из `system/lib64/`.

**Что делает утилита:**
1. Если на вход подан образ, он распаковывается без root-прав (через `debugfs` для EXT4 или `dump.erofs` для EROFS).
2. Находит целевые APK и копирует их в `output/`.
3. Анализирует строковые таблицы и DEX-байткод каждого APK на наличие зависимостей `com.miui.*`, `miui.*` и вызовов `System.loadLibrary`.
4. Извлекает соответствующие `.so` (arm64-v8a) из донорского `/system/lib64/`.
5. Автоматически генерирует `manifest.json` в целевой папке с готовой картой путей для инъекции.

---

## 3. `cli/patch_framework.py`
Инструмент smali-патчинга фреймворка Android (`framework.jar`, `services.jar`, `miui-services.jar`) или каталогов декомпилированных smali-файлов.

### 3.1. Патчинг каталога Smali (`dir`)
```bash
python3 cli/patch_framework.py dir --path extracted/smali
```
- Находит проверки подписей в `PackageManagerService.smali` (`compareSignatures`, `matchSignaturesCompat`, `checkSignatures`).
- Заменяет тело метода на возврат `SIGNATURE_MATCH = 0` или boolean `true` (`const/4 v0, 0x1`).
- Нейтрализует проверки свойств `ro.miui.*` и `ro.hyperos.*`.

### 3.2. Патчинг JAR-файла (`jar`)
```bash
python3 cli/patch_framework.py jar --input services.jar --output releases/services_patched.jar
```
- Извлекает `classes*.dex`. При наличии `baksmali` и `smali` выполняет полную декомпиляцию, модификацию и сборку; в противном случае выполняет безопасный DEX-хук.

### 3.3. Генерация заглушек (`stub`)
```bash
python3 cli/patch_framework.py stub --class-name com.miui.internal.util.DeviceHelper --output inject/smali/DeviceHelper.smali
```
- Создает валидный Smali-класс заглушки с методами, возвращающими безопасные значения (`false`, `0`, `null`, `void`).

---

## 4. `cli/inject_apks.py`
Внедрение APK, нативных библиотек `.so`, патчей системных свойств и правил SELinux в раздел системы.

### Использование
```bash
# Внедрение в распакованный каталог:
python3 cli/inject_apks.py --target extracted/super/system --inject inject/

# Внедрение напрямую в EXT4 system.img:
python3 cli/inject_apks.py --target system.img --output releases/system_injected.img --inject inject/

# Создание OTA ZIP архива для обновления:
python3 cli/inject_apks.py --inject inject/ --ota-zip releases/OrangeUI_Update_v1.0.zip
```
**Параметры:**
- `--target, -t`: Путь к каталогу раздела или образу `system.img`.
- `--output, -o`: Путь для сохранения модифицированного образа (если target — файл).
- `--inject, -i`: Входная папка с файлами и манифестом (по умолчанию `inject/`).
- `--manifest, -m`: Альтернативный путь к `manifest.json`.
- `--ota-zip`: Создать прошиваемый recovery/OTA ZIP-архив с обновлением.

---

## 5. `cli/build_gsi.py`
Автоматизированная сборка Generic System Image (GSI):
1. Скачивание архива GSI `.img.xz` по прямой ссылке с отображением прогресс-бара скорости и оставшегося времени.
2. Распаковка архива через `xz` или `lzma`.
3. Внедрение OrangeUI Liquid Glass APK и библиотек из `inject/`.
4. Опциональное наложение специфичных фиксов MediaTek (Charoite).

### Использование
```bash
# Сборка универсального Treble GSI:
python3 cli/build_gsi.py --url https://github.com/.../LineageOS-23.2_GSI.img.xz --inject inject/ --output releases/OrangeUI-GSI.img

# Сборка с фиксами для Xiaomi Charoite:
python3 cli/build_gsi.py --image gsi.img --charoite --output releases/charoite/system.img
```

---

## 6. `cli/charoite_builder.py`
Специализированный билдер для Redmi Note 15 Pro 4G (`xiaomi-charoite`, процессор MediaTek MT6789 Helio G99):
- Подтягивает фиксы Lights HAL, подсветки (`persist.sys.phh.backlight.scale=0`), NDK-библиотеки и Treble-оверлеи из `/mnt/loopfox/phones/charoite/Fabric/payload`.
- Создает flashable пакет `OrangeUI-charoite-v1.0.zip` со скриптами прошивки fastboot под Linux (`flash.sh`) и Windows (`flash.bat`).

### Использование
```bash
python3 cli/charoite_builder.py --output releases/charoite --version 1.0
```

---

## 7. `cli/manifest_parser.py`
Утилита валидации и генерации файлов `manifest.json`.

```bash
# Просмотр манифеста в виде красивой таблицы:
python3 cli/manifest_parser.py --manifest inject/manifest.json --show

# Строгая проверка существования всех исходных файлов:
python3 cli/manifest_parser.py --manifest inject/manifest.json --validate

# Автогенерация manifest.json на основе файлов в папке inject/:
python3 cli/manifest_parser.py --generate inject/
```
