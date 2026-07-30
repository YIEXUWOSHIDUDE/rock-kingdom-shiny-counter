from __future__ import annotations

import subprocess
import unittest

from shiny_counter.nvidia import query_nvidia_gpu


class NvidiaInventoryTests(unittest.TestCase):
    def test_nvidia_smi_name_and_driver_are_parsed(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="NVIDIA GeForce RTX 4070, 566.36\n",
                stderr="",
            )

        info = query_nvidia_gpu(run=run)

        self.assertIsNotNone(info)
        self.assertEqual("NVIDIA GeForce RTX 4070", info.name)
        self.assertEqual("566.36", info.driver_version)
        self.assertIn("name,driver_version", calls[0][1])

    def test_nvidia_smi_failure_returns_none(self) -> None:
        def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

        self.assertIsNone(query_nvidia_gpu(run=run))


if __name__ == "__main__":
    unittest.main()
