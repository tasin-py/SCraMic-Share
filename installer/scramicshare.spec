# Builds the app into dist/SCraMicShare with PyInstaller:  pyinstaller installer/scramicshare.spec
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "scramicshare.py")],
    pathex=[str(root)],
    datas=[
        (str(root / "web"), "web"),
        (str(root / "LICENSE"), "."),
        (str(root / "LICENSE-InkCast"), "."),
        (str(root / "NOTICE"), "."),
    ],
    hiddenimports=["qrcode.image.svg"],
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SCraMicShare",
    console=False,
    icon=str(root / "build" / "scramicshare.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="SCraMicShare")
