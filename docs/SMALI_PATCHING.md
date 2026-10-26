# 💉 Smali & Bytecode Patching Guide for OrangeUI

When porting Xiaomi HyperOS system applications to AOSP or Treble GSI bases, two primary compatibility hurdles arise:
1. **Signature Verification Mismatch:** Android PackageManagerService rejects OEM system applications that are signed with Xiaomi private keys or modified with custom resources.
2. **Missing MIUI API References:** HyperOS applications invoke proprietary classes in `miui.*` and `com.miui.*`, and query system properties such as `ro.miui.*` and `ro.hyperos.*`.

---

## 1. PackageManagerService Signature Bypass

In Android PMS, signature checking is performed within `compareSignatures`:

### Smali Bytecode Modification:
Original method signature:
```smali
.method public static compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
```

In AOSP PMS, returning `0` (`PackageManager.SIGNATURE_MATCH`) forces signature checks to succeed:
```smali
.method public static compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
    .registers 3

    const/4 v0, 0x0

    return v0
.end method
```
If the comparison method returns boolean (`...()Z`):
```smali
    .registers 3

    const/4 v0, 0x1

    return v0
```

Execute the automated patcher across decompiled smali trees:
```bash
python3 cli/patch_framework.py dir --path extracted/services_smali
```

---

## 2. Neutralizing System Property Checks (`ro.miui.*`)

HyperOS applications check the operating environment via `SystemProperties.get("ro.miui.ui.version.name")`. If unhandled, applications may throw exceptions or fail initialization.

The patcher substitutes `ro.miui.*` tokens with mock values, while `inject/build.prop.patch` injects default properties into `build.prop`:
```properties
persist.sys.orangeui.liquid_glass=1
persist.sys.orangeui.monet=0
ro.miui.ui.version.name=V816
ro.miui.ui.version.code=816
```

---

## 3. Generating Smali Stubs

For classes or methods that are missing in the target AOSP base:
- **Object types (`L...;`):** return `null` (`const/4 v0, 0x0`, `return-object v0`).
- **Primitives and booleans (`Z`, `I`, `J`):** return `0` / `false` (`const/4 v0, 0x0`, `return v0`).
- **Void (`V`):** return `return-void`.

### Stub Generation Command:
```bash
python3 cli/patch_framework.py stub \
  --class-name com.miui.internal.util.DeviceHelper \
  --output inject/stubs/DeviceHelper.smali
```

---

## 4. Reference Implementations & Tools
- **FrameworkPatcher:** Patches `framework.jar`, `services.jar`, `miui-services.jar`.
- **KaoriOS-RePatcher:** On-device smali bytecode patcher.
- **SRPatch-X:** PMS and IO hook toolkit.
- **CorePatch / LuckyPatcher:** Reference implementations for APK verification bypass.
