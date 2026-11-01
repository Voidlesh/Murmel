# PyInstaller spec for the Murmel engine. Build with packaging/build-engine.ps1.
# Output: build/engine-dist/murmel-engine/ (one folder, copied into the installer as resources/engine).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

ROOT = Path(SPECPATH).parent

# packages that load data files, native libraries or plugins at runtime
COLLECTED_PACKAGES = [
    "faster_whisper",
    "ctranslate2",
    "av",
    "onnxruntime",
    "tokenizers",
    "sounddevice",
    "comtypes",
    "pycaw",
    "websockets",
]
# pip's nvidia-* wheels: the CUDA DLLs that engine/stt.py registers at runtime
CUDA_PACKAGES = ["nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"]

datas, binaries, hiddenimports = [], [], []
for package in COLLECTED_PACKAGES:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
for package in CUDA_PACKAGES:
    binaries += collect_dynamic_libs(package)

a = Analysis(
    [str(ROOT / "packaging" / "engine_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="murmel-engine",
    console=False,  # started hidden by the Electron app, no console window
    icon=str(ROOT / "app" / "assets" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="murmel-engine")
