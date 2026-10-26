# 💉 Руководство по Smali-патчингу фреймворка для OrangeUI

При портировании приложений HyperOS в AOSP / Treble GSI возникают две ключевые проблемы:
1. **Несовпадение цифровых подписей:** AOSP отклоняет запуск системных приложений, подписанных сертификатами Xiaomi, либо приложений с замененными ресурсами.
2. **Отсутствие MIUI API:** приложения HyperOS обращаются к закрытым методам классов `miui.*` и `com.miui.*`, а также проверяют свойства `ro.miui.*` / `ro.hyperos.*`.

---

## 1. Отключение проверки подписей (PMS Signature Bypass)

В Android служба управления пакетами `PackageManagerService` сверяет сертификаты в методе `compareSignatures`.

### Реализация в `cli/patch_framework.py`:
Метод патчера находит сигнатуру метода:
```smali
.method public static compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
```
В AOSP метод должен возвращать `0` (`PackageManager.SIGNATURE_MATCH`):
```smali
.method public static compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
    .registers 3

    const/4 v0, 0x0

    return v0
.end method
```
Если метод возвращает булево значение (`...()Z`):
```smali
    .registers 3

    const/4 v0, 0x1

    return v0
```

Запуск автоматического патчера:
```bash
python3 cli/patch_framework.py dir --path extracted/services_smali
```

---

## 2. Нейтрализация проверок системных свойств (`ro.miui.*`)

HyperOS-приложения проверяют окружение через `SystemProperties.get("ro.miui.ui.version.name")` или похожие ключи. Если они пустые, приложение может аварийно завершиться.

Патчер заменяет строковые константы `ro.miui.*` на заглушки или редиректы, а файл `inject/build.prop.patch` внедряет фиктивные значения в систему:
```properties
persist.sys.orangeui.liquid_glass=1
persist.sys.orangeui.monet=0
ro.miui.ui.version.name=V816
ro.miui.ui.version.code=816
```

---

## 3. Генерация Smali-заглушек (Stubs)

Если приложению требуется класс или метод из `miui-framework`, которого нет в AOSP, создается smali-класс заглушка.

Правила формирования заглушек:
- **Объекты (`Ljava/lang/...;`):** возвращают `null` (`const/4 v0, 0x0`, `return-object v0`).
- **Числа и булевы значения (`Z`, `I`, `J`):** возвращают `0` / `false` (`const/4 v0, 0x0`, `return v0`).
- **Void (`V`):** пустой возврат (`return-void`).

### Пример команды генерации:
```bash
python3 cli/patch_framework.py stub \
  --class-name com.miui.internal.util.DeviceHelper \
  --output inject/stubs/DeviceHelper.smali
```

---

## 4. Референсные решения индустрии

- **FrameworkPatcher:** классический патчер `framework.jar`, `services.jar`, `miui-services.jar`.
- **KaoriOS-RePatcher:** инструмент on-device smali patching.
- **SRPatch-X:** библиотека перехватов PMS и файлового ввода-вывода (IO hook).
- **CorePatch / LuckyPatcher:** референсные хуки валидации APK-подписей и даунгрейда версий.
