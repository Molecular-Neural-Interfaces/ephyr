import sys
import os
sys.path.append(os.path.join(os.getcwd()))
from src.version import __version__

block_cipher = None

extra_dirs = [
    ('devtools/distribute/assets/weegit.png', 'weegit_assets/'),
]

a = Analysis(
    ['src/entrypoint.py'],
    pathex=[],
    binaries=[],
    datas=extra_dirs,
    hiddenimports=[],
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
    name='weegit',
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
    icon=['devtools/distribute/assets/weegit.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='weegit',
)
app = BUNDLE(
    coll,
    name='weegit.app',
    icon='devtools/distribute/assets/weegit.png',
    bundle_identifier='center.lift.weegit',
    version=__version__,
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'LSBackgroundOnly': False,
        'NSRequiresAquaSystemAppearance': 'No',
        'CFBundleIdentifier': 'center.lift.weegit',
        'CFBundlePackageType': 'APPL',
        'CFBundleSupportedPlatforms': ['MacOSX'],
        'CFBundleVersion': __version__
    },
)