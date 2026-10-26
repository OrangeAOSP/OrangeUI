# 📦 Извлечение приложений и библиотек из HyperOS

Руководство по извлечению системных компонентов стоковых прошивок Xiaomi HyperOS для портирования в OrangeUI Liquid Glass.

---

## 1. Подготовка донорской прошивки

Для извлечения приложений вам потребуется официальная стоковая прошивка HyperOS (Fastboot ROM или Recovery ROM):
- Для Fastboot ROM: внутри архива находится файл `super.img` или `images/system.img`.
- Для Recovery ROM: внутри архива `payload.bin`, распаковать который можно утилитой `payload-dumper-go`.

---

## 2. Шаг 1: Распаковка разделов

Если у вас на руках `super.img`:
```bash
python3 cli/repack_super.py unpack --input /path/to/hyperos/super.img --output extracted/hyperos
```
Скрипт автоматически определит тип `super.img` (sparse/raw), извлечет разделы `system`, `vendor`, `product` и определит их файловую систему (EXT4 или EROFS).

---

## 3. Шаг 2: Извлечение системных APK

Запустите утилиту автоматического извлечения и анализа зависимостей:
```bash
python3 cli/extract_hyperos.py \
  --system extracted/hyperos/system.img \
  --output inject/ \
  --targets MiuiHome Settings MiuiSystemUI ThemeManager
```

### Ключевые приложения HyperOS:
1. **Лаунчер (Рабочий стол):**
   - Путь в HyperOS: `/system/priv-app/MiuiHome/MiuiHome.apk`
   - Особенности: отвечает за жесты навигации, анимацию открывания приложений, сетку иконок и виджеты.
2. **Панель управления и шторка (SystemUI):**
   - Путь в HyperOS: `/system/priv-app/MiuiSystemUI/MiuiSystemUI.apk`
   - Особенности: содержит фирменный центр управления Liquid Glass.
3. **Настройки (Settings):**
   - Путь в HyperOS: `/system/priv-app/Settings/Settings.apk`
4. **Темы оформления (ThemeManager):**
   - Путь в HyperOS: `/system/app/ThemeManager/ThemeManager.apk`

---

## 4. Шаг 3: Автоматический сбор нативных библиотек (.so)

Многие приложения HyperOS (особенно `MiuiHome` и `MiuiSystemUI`) зависят от проприетарных C++ библиотек.
Скрипт `cli/extract_hyperos.py`:
1. Сканирует DEX-байткод извлеченных приложений.
2. Ищет вызовы `System.loadLibrary(...)`.
3. Анализирует зависимости ELF `DT_NEEDED`.
4. Автоматически находит и копирует только 64-битные версии (`arm64-v8a`) из `/system/lib64/` прошивки-донора в папку `inject/lib64/`.

Типичные библиотеки HyperOS:
- `libthemeutils_jni.so`
- `libshell_transition_jni.so`
- `libblur_jni.so` (алгоритмы размытия Liquid Glass)

---

## 5. Шаг 4: Формирование manifest.json

Скрипт `extract_hyperos.py` сразу генерирует готовый файл `inject/manifest.json`:
```json
{
  "MiuiHome.apk": "/system/priv-app/MiuiHome/MiuiHome.apk",
  "Settings.apk": "/system/priv-app/Settings/Settings.apk",
  "lib64/libblur_jni.so": "/system/lib64/libblur_jni.so"
}
```

Проверить валидность сгенерированного манифеста можно командой:
```bash
python3 cli/manifest_parser.py --manifest inject/manifest.json --validate
```
