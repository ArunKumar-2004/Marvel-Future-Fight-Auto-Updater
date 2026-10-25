# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],  # Make sure your script is named app.py
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore', 
        'PySide6.QtMultimedia', 'PySide6.Qt3DCore', 'PySide6.QtQuick',
        'PySide6.QtQml', 'PySide6.QtNetwork', 'PySide6.QtSql',
        'PySide6.QtTest', 'PySide6.QtXml', 'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'tkinter', 'unittest', 'pydoc'
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MFF_Auto_Modder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)