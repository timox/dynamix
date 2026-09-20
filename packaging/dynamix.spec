# PyInstaller recipe of the shareable Windows build of DynaMix.
# Build with packaging\build_windows.bat (or, from the repository root:
#   venv\Scripts\python -m PyInstaller packaging\dynamix.spec --noconfirm)
# Result: dist\DynaMix\DynaMix.exe and its _internal folder; zip dist\DynaMix to share it.

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH is set by PyInstaller

# Never used by DynaMix: left out to keep the build small.
EXCLUDES = [
    "pandas", "sklearn", "IPython", "jupyter_client", "jupyter_core", "notebook", "nbformat",
    "pytest", "_pytest", "sphinx", "docutils", "pyflakes", "PyInstaller",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi",
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qt5agg", "matplotlib.backends.backend_wxagg",
    "matplotlib.backends.backend_gtk3agg", "matplotlib.backends.backend_gtk4agg", "matplotlib.backends.backend_webagg",
    "matplotlib.backends.backend_nbagg", "matplotlib.backends.backend_macosx",
    "tkinter.test", "lib2to3", "pydoc_data", "xmlrpc",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "gui.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "locales"), "locales")],  # translations (i18n.package_dir)
    hiddenimports=["selftest", "version"],  # both imported inside functions, not at module level
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DynaMix",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DynaMix", upx=False)  # noqa: F821
