import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).parent
model_directory = Path(os.environ["RKSC_MODEL_DIR"]).resolve()
probe_image = Path(os.environ["RKSC_PROBE_IMAGE"]).resolve()
required_models = [
    model_directory / "craft_mlt_25k.pth",
    model_directory / "zh_sim_g2.pth",
]
for model in required_models:
    if not model.is_file():
        raise SystemExit(f"OCR model is missing: {model}")
if not probe_image.is_file():
    raise SystemExit(f"OCR probe image is missing: {probe_image}")

datas = [
    (str(project_root / "VERSION"), "."),
    (str(project_root / "ocr-models.lock.json"), "."),
    *[(str(model), "ocr-models") for model in required_models],
    (str(probe_image), "ocr-probe"),
    *collect_data_files("easyocr"),
]
hiddenimports = sorted(
    set(
        collect_submodules("easyocr")
        + collect_submodules("torchvision")
        + [
            "cv2",
            "mss.windows",
            "win32gui",
            "win32process",
        ]
    )
)

a = Analysis(
    [str(project_root / "packaging" / "launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RockKingdomShinyCounter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RockKingdomShinyCounter",
)
