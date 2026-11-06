import sys
import os
sys.path.append(os.path.join(os.getcwd()))
from ephyr.version import __version__
from PyInstaller.utils.hooks import collect_all, collect_data_files


block_cipher = None

hdmf_datas = collect_data_files('hdmf')
pynwb_datas = collect_data_files('pynwb')

# Standalone installs add-ons in-process. pip has to travel with the application,
# including its package data, so a machine without Python can still download wheels.
pip_datas, pip_binaries, pip_hidden = collect_all('pip')

extra_dirs = [
    ('devtools/distribute/assets/ephyr.png', 'ephyr_assets/'),

    # include package_data for ephyr.gui = assets/*
    ('ephyr/gui/assets/*', 'ephyr/gui/assets'),
    ('ephyr/core/add_ons/template', 'ephyr/core/add_ons/template'),

    # add the collected data files from dependencies
    *hdmf_datas,
    *pynwb_datas,
]

a = Analysis(
    ['ephyr/gui/entrypoint.py'],
    pathex=[],
    binaries=pip_binaries,
    datas=extra_dirs + pip_datas,
    hiddenimports=pip_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ephyr',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # always build for current OS
    codesign_identity=None,
    entitlements_file=None,
    icon=['devtools/distribute/assets/ephyr.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ephyr',
)
app = BUNDLE(
    coll,
    name='ephyr.app',
    icon='devtools/distribute/assets/ephyr.png',
    bundle_identifier='center.lift.ephyr',
    version=__version__,
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'LSBackgroundOnly': False,
        'NSRequiresAquaSystemAppearance': 'No',
        'CFBundleIdentifier': 'center.lift.ephyr',
        'CFBundlePackageType': 'APPL',
        'CFBundleSupportedPlatforms': ['MacOSX'],
        'CFBundleVersion': __version__
    },
)