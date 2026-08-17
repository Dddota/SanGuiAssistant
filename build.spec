# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: 三归小助手 (onedir)
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], []

# qfluentwidgets: qss 样式表 + 内嵌图标资源，必须整体收集
qf_datas, qf_binaries, qf_hidden = collect_all("qfluentwidgets")
datas += qf_datas
binaries += qf_binaries
hiddenimports += qf_hidden

# MaaFw 原生 DLL（AdbController 运行时加载），随程序分发
maa_binaries = collect_dynamic_libs("maa")
binaries += maa_binaries

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SanguiHelper",
    icon="app_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
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
    upx=True,
    upx_exclude=[],
    name="SanguiHelper",
)