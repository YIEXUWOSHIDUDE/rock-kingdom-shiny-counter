"""Rock Kingdom shiny pity counter."""

from pathlib import Path


def _load_version() -> str:
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        version = version_file.read_text(encoding="ascii").strip()
    except OSError as error:
        raise RuntimeError(f"安装包缺少 VERSION：{error}") from error
    if not version:
        raise RuntimeError("VERSION 不能为空")
    return version


__version__ = _load_version()
