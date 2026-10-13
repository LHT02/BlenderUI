# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded UWP manifest/asset resolution; no application launches or Shell APIs."""
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import package_icons as icons

APP = 'Example.Package_abcd123456789!ExampleApp'


class PackageIconTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='blui_package_icons_test_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'Assets').mkdir()
        patch = mock.patch.object(icons, '_installed_roots', return_value=[str(self.root)])
        patch.start()
        self.addCleanup(patch.stop)

    def png(self, filename, width=256, height=256):
        path = self.root / 'Assets' / filename
        path.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', width, height))
        return str(path.resolve())

    def manifest(self, logo='Assets\\SmallLogo.png', application='ExampleApp', extra=''):
        (self.root / 'AppxManifest.xml').write_text(
            '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10" '
            'xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"><Applications>'
            + extra + '<Application Id="' + application + '"><uap:VisualElements Square44x44Logo="'
            + logo + '"/></Application></Applications></Package>', encoding='utf-8')

    def test_identity_rejects_paths_commands_missing_application(self):
        for value in ('', None, 'not-an-app', 'x!y!z', '../Package_abcd!App', 'Package_abcd!../../file',
                      'Package_abcd!App && cmd', 'Package_abcd!App\x00', 'x' * 600 + '!App'):
            self.assertIsNone(icons.split_app_id(value), value)
            self.assertIsNone(icons.resolve(value), value)
        self.assertEqual(icons.split_app_id(APP), ('Example.Package_abcd123456789', 'ExampleApp'))

    def test_prefers_large_unplated_taskbar_asset(self):
        self.manifest()
        self.png('SmallLogo.png', 44, 44)
        self.png('SmallLogo.scale-400.png', 176, 176)
        self.png('SmallLogo.targetsize-16_altform-unplated.png', 16, 16)
        self.png('SmallLogo.targetsize-256.png')
        expected = self.png('SmallLogo.targetsize-256_altform-unplated.png')
        self.assertEqual(icons.resolve(APP), expected)

    def test_virtual_base_asset_qualified_only_supported(self):
        self.manifest()
        expected = self.png('SmallLogo.scale-200.png', 88, 88)
        self.assertEqual(icons.resolve(APP), expected)

    def test_common_icon_probed_independent_of_large_directory_order(self):
        self.manifest()
        expected = self.png('SmallLogo.targetsize-256_altform-unplated.png')
        # A bounded scan can terminate before this asset; direct documented names
        # still locate it without walking an unbounded package asset directory.
        empty_scan = mock.MagicMock()
        empty_scan.__enter__.return_value = []
        with mock.patch.object(icons.os, 'scandir', return_value=empty_scan):
            self.assertEqual(icons.resolve(APP), expected)

    def test_exact_application_matching_not_other_app(self):
        extra = '<Application Id="OtherApp"><uap:VisualElements Square44x44Logo="Assets/Other.png"/></Application>'
        self.manifest(extra=extra)
        self.png('Other.targetsize-256_altform-unplated.png')
        expected = self.png('SmallLogo.png', 44, 44)
        self.assertEqual(icons.resolve(APP), expected)
        self.assertIsNone(icons.resolve('Example.Package_abcd123456789!Absent'))

    def test_escape_absolute_unc_and_invalid_asset_rejected(self):
        self.png('SmallLogo.png')
        for logo in ('../Assets/SmallLogo.png', '/Assets/SmallLogo.png', 'C:\\Assets\\SmallLogo.png',
                     '\\\\host\\SmallLogo.png', 'Assets//SmallLogo.png', 'Assets/%x.png'):
            self.manifest(logo=logo)
            self.assertIsNone(icons.resolve(APP), logo)

    def test_doctype_entities_and_oversize_manifest_rejected(self):
        for data in ('<!DOCTYPE x [<!ENTITY boom "expanded">]><Package/>', 'x' * (icons.MAX_MANIFEST + 1)):
            (self.root / 'AppxManifest.xml').write_text(data, encoding='utf-8')
            self.assertIsNone(icons.resolve(APP))

    def test_utf16_manifest_supported_but_utf16_dtd_rejected(self):
        self.manifest()
        manifest = self.root / 'AppxManifest.xml'
        content = manifest.read_text(encoding='utf-8')
        manifest.write_bytes(content.encode('utf-16'))
        expected = self.png('SmallLogo.png')
        self.assertEqual(icons.resolve(APP), expected)
        manifest.write_bytes('<!DOCTYPE x [<!ENTITY a "expanded">]><Package/>'.encode('utf-16'))
        self.assertIsNone(icons.resolve(APP))

    def test_missing_invalid_png_and_overlarge_dimensions_fail_neutral(self):
        self.manifest()
        self.assertIsNone(icons.resolve(APP))
        self.png('SmallLogo.png', 4096, 4096)
        self.assertIsNone(icons.resolve(APP))
        (self.root / 'Assets/SmallLogo.png').write_bytes(b'not real png')
        self.assertIsNone(icons.resolve(APP))

    def test_highcontrast_light_variant_does_not_replace_normal_icon(self):
        self.manifest()
        expected = self.png('SmallLogo.png', 44, 44)
        self.png('SmallLogo.contrast-black_targetsize-256.png')
        self.png('SmallLogo.targetsize-256_altform-lightunplated.png')
        self.assertEqual(icons.resolve(APP), expected)

    def test_api_errors_fail_closed(self):
        with mock.patch.object(icons, '_installed_roots', side_effect=OSError('no package')):
            self.assertIsNone(icons.resolve(APP))


class PackageApiBoundsTests(unittest.TestCase):
    def query(self, count_value, length_value, *, second_status=0):
        calls = []
        def packages(family, count, names, length, buffer):
            calls.append(names is None)
            if names is None:
                count._obj.value, length._obj.value = count_value, length_value
                return 122
            if second_status:
                return second_status
            names[0] = 'Example.Package_1.0_x64__abcd123456789'
            return 0
        def package_path(name, length, buffer):
            if buffer is None:
                length._obj.value = 100
                return 122
            buffer.value = r'C:\Program Files\WindowsApps\Example.Package'
            return 0
        kernel = SimpleNamespace(GetPackagesByPackageFamily=packages, GetPackagePathByFullName=package_path)
        with mock.patch.object(icons.os, 'name', 'nt'), mock.patch.object(icons, '_kernel', return_value=kernel):
            result = icons._installed_roots('Example.Package_abcd123456789')
        return result, calls

    def test_bounded_double_call_package_path(self):
        result, calls = self.query(1, 100)
        self.assertEqual(result, [r'C:\Program Files\WindowsApps\Example.Package'])
        self.assertEqual(calls, [True, False])

    def test_unreasonable_api_buffer_sizes_do_not_allocate_or_call_again(self):
        for count, length in ((0, 100), (65, 100), (1, 0), (1, 65537)):
            result, calls = self.query(count, length)
            self.assertEqual(result, [])
            self.assertEqual(calls, [True])

    def test_package_removed_during_query_fails_closed(self):
        result, calls = self.query(1, 100, second_status=1168)
        self.assertEqual(result, [])
        self.assertEqual(calls, [True, False])


if __name__ == '__main__':
    unittest.main()
