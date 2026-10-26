#!/usr/bin/env python3
"""
OrangeUI Integration & Unit Tests
Verifies:
1. Manifest parsing & validation
2. Smali signature patching and stub generation
3. Super partition repacking with lpmake & lpunpack
4. Asset injection and OTA zip generation
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cli.inject_apks import generate_ota_update_zip, inject_into_tree
from cli.manifest_parser import ManifestParser
from cli.patch_framework import generate_smali_class_stub, patch_smali_directory, patch_smali_props, patch_smali_signature_checks
from cli.repack_super import repack_super, unpack_super
from cli.utils.deps import check_command
from cli.utils.fs import build_ext4_image, detect_filesystem


class TestOrangeUIPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="orangeui_test_"))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_01_manifest_parser(self):
        """Test manifest generation and parsing."""
        inject_dir = self.test_dir / "inject"
        inject_dir.mkdir()
        (inject_dir / "TestApp.apk").write_bytes(b"dummy_apk")
        lib64_dir = inject_dir / "lib64"
        lib64_dir.mkdir()
        (lib64_dir / "libtest.so").write_bytes(b"dummy_so")

        manifest_file = ManifestParser.generate_from_dir(inject_dir)
        self.assertTrue(manifest_file.is_file())

        manifest = ManifestParser.load(manifest_file)
        self.assertEqual(len(manifest.entries), 2)
        valid, errors = manifest.validate()
        self.assertTrue(valid)
        self.assertEqual(len(errors), 0)

    def test_02_smali_patching(self):
        """Test PMS signature bypass and prop redirection."""
        sample_smali = """
.class public Lcom/android/server/pm/PackageManagerService;
.super Ljava/lang/Object;

.method public static compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
    .registers 3
    # original signature comparison logic
    const/4 v0, 0x1
    return v0
.end method

.method public checkProp()V
    .registers 2
    const-string v0, "ro.miui.ui.version.name"
    return-void
.end method
"""
        patched_sig, sig_count = patch_smali_signature_checks(sample_smali)
        self.assertEqual(sig_count, 1)
        self.assertIn("const/4 v0, 0x0", patched_sig)

        patched_prop, prop_count = patch_smali_props(sample_smali)
        self.assertEqual(prop_count, 1)
        self.assertIn("ro.orangeui.dummy", patched_prop)

        # Test stub generation
        stub = generate_smali_class_stub("com.miui.internal.DummyHelper")
        self.assertIn(".class public Lcom/miui/internal/DummyHelper;", stub)
        self.assertIn("isFeatureSupported", stub)

    def test_03_repack_super_e2e(self):
        """Test lpmake and lpunpack end-to-end with ext4 partitions."""
        if not check_command("lpmake") or not check_command("lpunpack"):
            self.skipTest("lpmake or lpunpack not installed")

        parts_dir = self.test_dir / "partitions"
        parts_dir.mkdir()

        # Create dummy partition files (4MB each)
        for part_name in ["system", "vendor", "product"]:
            img_file = parts_dir / f"{part_name}.img"
            img_file.write_bytes(b"\x00" * (4 * 1024 * 1024))

        output_super = self.test_dir / "releases" / "super.img"
        # Repack super
        repack_super(
            input_dir=parts_dir,
            output_super=output_super,
            device_size=32 * 1024 * 1024,
            sparse=False
        )
        self.assertTrue(output_super.is_file())
        self.assertGreater(output_super.stat().st_size, 0)

        # Unpack super
        unpacked_dir = self.test_dir / "unpacked"
        unpack_super(
            super_img=output_super,
            output_dir=unpacked_dir,
            target_partitions=["system", "vendor", "product"]
        )

        for part_name in ["system", "vendor", "product"]:
            extracted_img = unpacked_dir / f"{part_name}.img"
            self.assertTrue(extracted_img.is_file(), f"Missing extracted {part_name}.img")

    def test_04_injection_and_ota(self):
        """Test asset injection and OTA update package generation."""
        system_tree = self.test_dir / "system_tree"
        (system_tree / "system" / "priv-app").mkdir(parents=True)
        (system_tree / "system" / "build.prop").write_text("ro.product.model=AOSP\n")

        inject_dir = self.test_dir / "inject"
        inject_dir.mkdir()
        (inject_dir / "OrangeUI_Launcher.apk").write_bytes(b"apk_data")
        (inject_dir / "build.prop.patch").write_text("persist.sys.orangeui.liquid_glass=1\n")

        manifest_data = {
            "OrangeUI_Launcher.apk": "/system/priv-app/Launcher/Launcher.apk"
        }
        import json
        with open(inject_dir / "manifest.json", "w") as f:
            json.dump(manifest_data, f)

        # Inject into tree
        injected_count = inject_into_tree(system_tree, inject_dir)
        self.assertEqual(injected_count, 1)

        dest_apk = system_tree / "system" / "priv-app" / "Launcher" / "Launcher.apk"
        self.assertTrue(dest_apk.is_file())
        self.assertIn("persist.sys.orangeui.liquid_glass=1", (system_tree / "system" / "build.prop").read_text())

        # Generate OTA zip
        ota_zip = self.test_dir / "OrangeUI_Update.zip"
        generate_ota_update_zip(inject_dir, ota_zip)
        self.assertTrue(ota_zip.is_file())
        self.assertGreater(ota_zip.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
