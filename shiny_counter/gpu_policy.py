from __future__ import annotations

import re
from typing import Any


EXPECTED_TORCH_VERSION = "2.13.0"
EXPECTED_CUDA_BUILD = "13.0"
EXPECTED_TORCHVISION_VERSION = "0.28.0"
REQUIRED_RELEASE_ARCHITECTURES = {"sm_75", "sm_86", "sm_120"}


class GPUCompatibilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_release_cuda_build(torch_module: Any) -> dict[str, Any]:
    torch_version = str(torch_module.__version__)
    cuda_version = str(torch_module.version.cuda)
    if torch_version.split("+", 1)[0] != EXPECTED_TORCH_VERSION:
        raise GPUCompatibilityError(
            "CUDA_RUNTIME_UNSUPPORTED",
            f"发布环境必须使用 torch {EXPECTED_TORCH_VERSION}，"
            f"当前为 {torch_version}"
        )
    if cuda_version != EXPECTED_CUDA_BUILD or "+cu130" not in torch_version:
        raise GPUCompatibilityError(
            "CUDA_RUNTIME_UNSUPPORTED",
            f"发布环境必须使用官方 CUDA {EXPECTED_CUDA_BUILD} 构建，当前为 "
            f"torch {torch_version} / CUDA {cuda_version}"
        )
    architectures = sorted(map(str, torch_module.cuda.get_arch_list()))
    missing = sorted(REQUIRED_RELEASE_ARCHITECTURES.difference(architectures))
    if missing:
        raise GPUCompatibilityError(
            "CUDA_ARCH_UNSUPPORTED",
            "PyTorch wheel 缺少项目声明支持的架构：" + ", ".join(missing)
        )
    return {
        "torch": torch_version,
        "cuda": cuda_version,
        "architectures": architectures,
    }


def validate_cuda_device(torch_module: Any) -> str:
    if not torch_module.cuda.is_available():
        raise GPUCompatibilityError(
            "CUDA_UNAVAILABLE",
            "未检测到可用的 NVIDIA CUDA。最低要求：RTX 20 系显卡、"
            "Windows NVIDIA 驱动 580.88；本程序不支持 CPU 模式。"
        )
    capability = tuple(torch_module.cuda.get_device_capability())
    device_name = str(torch_module.cuda.get_device_name())
    if capability < (7, 5):
        raise GPUCompatibilityError(
            "CUDA_ARCH_UNSUPPORTED",
            f"显卡 {device_name} 的 CUDA 计算能力 "
            f"{capability[0]}.{capability[1]} 低于最低要求 7.5（RTX 20 系）。"
        )
    architecture = f"sm_{capability[0]}{capability[1]}"
    supported_architectures = set(torch_module.cuda.get_arch_list())
    same_major_compatible = any(
        (match := re.fullmatch(r"sm_(\d+)(\d)", candidate))
        and int(match.group(1)) == capability[0]
        and int(match.group(2)) <= capability[1]
        for candidate in supported_architectures
    )
    if not same_major_compatible:
        raise GPUCompatibilityError(
            "CUDA_ARCH_UNSUPPORTED",
            f"当前 PyTorch CUDA 运行库不包含 {architecture}，"
            f"无法使用 {device_name}。RTX 50 系需要 CUDA 13.0 兼容版安装包。"
        )
    return f"CUDA · {device_name} · {architecture}"
