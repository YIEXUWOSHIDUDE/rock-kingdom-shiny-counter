import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_tools.package_installer import (
    FOOTER_MAGIC,
    append_payload,
    create_payload,
    read_appended_payload,
    verify_directory_manifest,
    write_directory_manifest,
)
from build_tools.run_frozen_probe import resolve_probe_paths


class ReleasePackagingTests(unittest.TestCase):
    def test_frozen_probe_resolves_report_before_changing_working_directory(
        self,
    ) -> None:
        executable, report = resolve_probe_paths(
            Path("release/staging/App/App.exe"),
            Path("release/out/probe.json"),
        )

        self.assertTrue(executable.is_absolute())
        self.assertTrue(report.is_absolute())
        self.assertEqual(report.name, "probe.json")

    def test_payload_zip_is_deterministic_and_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app"
            source.mkdir()
            (source / "z.txt").write_text("last", encoding="utf-8")
            (source / "a.txt").write_text("first", encoding="utf-8")
            first = root / "first.zip"
            second = root / "second.zip"

            create_payload(source, first)
            create_payload(source, second)

            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), ["a.txt", "z.txt"])

    def test_appended_installer_payload_can_be_read_back_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stub = root / "stub.exe"
            payload = root / "payload.zip"
            output = root / "setup.exe"
            stub.write_bytes(b"MZ-test-stub")
            payload.write_bytes(b"PK-test-payload")

            append_payload(stub, payload, output)

            self.assertTrue(output.read_bytes().endswith(FOOTER_MAGIC))
            self.assertEqual(read_appended_payload(output), payload.read_bytes())

    def test_directory_manifest_rejects_tampered_cached_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "torch-test.whl"
            wheel.write_bytes(b"trusted-wheel")
            manifest = root / "MANIFEST.sha256.json"
            write_directory_manifest(root, manifest)
            verify_directory_manifest(root, manifest)

            wheel.write_bytes(b"tampered-wheel")

            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify_directory_manifest(root, manifest)


if __name__ == "__main__":
    unittest.main()
