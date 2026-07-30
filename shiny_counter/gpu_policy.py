from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


EXPECTED_TORCH_VERSION = "2.11.0"
EXPECTED_CUDA_BUILD = "12.8"
EXPECTED_CUDA_TAG = "cu128"
EXPECTED_TORCHVISION_VERSION = "0.26.0"
MINIMUM_WINDOWS_DRIVER = (570, 65)
MINIMUM_WINDOWS_DRIVER_TEXT = "570.65"
REQUIRED_RELEASE_ARCHITECTURES = {"sm_75", "sm_86", "sm_120"}


class GPUCompatibilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NvidiaGPUInfo:
    name: str
    driver_version: str


def driver_at_least(
    version: str,
    minimum: tuple[int, int] = MINIMUM_WINDOWS_DRIVER,
) -> bool:
    match = re.match(r"^(\d+)\.(\d+)", version.strip())
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= minimum


def cuda_unavailable_error(
    nvidia_info: NvidiaGPUInfo | None,
) -> GPUCompatibilityError:
    if nvidia_info is not None and nvidia_info.driver_version:
        if not driver_at_least(nvidia_info.driver_version):
            return GPUCompatibilityError(
                "CUDA_DRIVER_TOO_OLD",
                f"识别未启动：{nvidia_info.name} 驱动 "
                f"{nvidia_info.driver_version} 过旧，请升级到 "
                f"{MINIMUM_WINDOWS_DRIVER_TEXT} 或更高。"
                "本程序只使用 GPU，不会切换到 CPU。",
            )
        return GPUCompatibilityError(
            "CUDA_RUNTIME_UNAVAILABLE",
            f"识别未启动：已检测到 {nvidia_info.name} / 驱动 "
            f"{nvidia_info.driver_version}，但 CUDA {EXPECTED_CUDA_BUILD} 无法启动；"
            "请重启电脑，仍失败则重装 GPU 版。本程序不会切换到 CPU。",
        )
    return GPUCompatibilityError(
        "CUDA_UNAVAILABLE",
        "未检测到可用的 NVIDIA CUDA。最低要求：RTX 20 系显卡、"
        f"Windows NVIDIA 驱动 {MINIMUM_WINDOWS_DRIVER_TEXT}；"
        "本程序不支持 CPU 模式，也不允许 CPU 回退。",
    )


def validate_release_cuda_build(torch_module: Any) -> dict[str, Any]:
    torch_version = str(torch_module.__version__)
    cuda_version = str(torch_module.version.cuda)
    if torch_version.split("+", 1)[0] != EXPECTED_TORCH_VERSION:
        raise GPUCompatibilityError(
            "CUDA_RUNTIME_UNSUPPORTED",
            f"发布环境必须使用 torch {EXPECTED_TORCH_VERSION}，"
            f"当前为 {torch_version}"
        )
    if (
        cuda_version != EXPECTED_CUDA_BUILD
        or f"+{EXPECTED_CUDA_TAG}" not in torch_version
    ):
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


def validate_cuda_device(
    torch_module: Any,
    *,
    nvidia_info: NvidiaGPUInfo | None = None,
) -> str:
    if not torch_module.cuda.is_available():
        raise cuda_unavailable_error(nvidia_info)
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
            f"无法使用 {device_name}。请安装 CUDA {EXPECTED_CUDA_BUILD} GPU 版。"
        )
    return f"CUDA · {device_name} · {architecture}"
