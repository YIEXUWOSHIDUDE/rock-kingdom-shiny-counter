import types
import unittest

from build_tools.release_validation import validate_cuda_release


class ReleaseValidationTests(unittest.TestCase):
    def test_cuda_130_build_is_rejected(self) -> None:
        torch_module = types.SimpleNamespace(
            __version__="2.11.0+cu130",
            version=types.SimpleNamespace(cuda="13.0"),
            cuda=types.SimpleNamespace(
                get_arch_list=lambda: ["sm_75", "sm_86", "sm_120"],
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "CUDA 12\\.8"):
            validate_cuda_release(torch_module)

    def test_release_requires_all_advertised_rtx_architectures(self) -> None:
        torch_module = types.SimpleNamespace(
            __version__="2.11.0+cu128",
            version=types.SimpleNamespace(cuda="12.8"),
            cuda=types.SimpleNamespace(
                get_arch_list=lambda: ["sm_75", "sm_86", "sm_90"],
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "sm_120"):
            validate_cuda_release(torch_module)

    def test_pinned_cuda_128_build_with_required_architectures_passes(self) -> None:
        torch_module = types.SimpleNamespace(
            __version__="2.11.0+cu128",
            version=types.SimpleNamespace(cuda="12.8"),
            cuda=types.SimpleNamespace(
                get_arch_list=lambda: ["sm_75", "sm_86", "sm_120"],
            ),
        )

        report = validate_cuda_release(torch_module)

        self.assertEqual(report["torch"], "2.11.0+cu128")
        self.assertEqual(report["cuda"], "12.8")


if __name__ == "__main__":
    unittest.main()
