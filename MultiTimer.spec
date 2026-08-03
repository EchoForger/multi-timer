# -*- mode: python ; coding: utf-8 -*-
# 用法: pyinstaller MultiTimer.spec --noconfirm  ->  产物在 dist/MultiTimer.app

a = Analysis(
    ['multitimer.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/app-icon.png', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6',
        'PyQt5',
        'PyQt6',
        'tkinter',
        'numpy',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MultiTimer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MultiTimer',
)
app = BUNDLE(
    coll,
    name='MultiTimer.app',
    icon='assets/MultiTimer.icns',
    bundle_identifier='io.github.echoforger.multitimer.statusbar',
    info_plist={
        'LSUIElement': True,               # 纯菜单栏应用, 不显示 Dock 图标
        'NSHighResolutionCapable': True,
        'CFBundleName': 'MultiTimer',
        'CFBundleDisplayName': 'MultiTimer',
        'CFBundleShortVersionString': '0.3.7',
        'CFBundleVersion': '0.3.7',
        'NSHumanReadableCopyright': '© 2026 EchoForger · MIT License',
    },
)
