# rml_tools.spec
# Build with:  pyinstaller rml_tools.spec
#
# Bundles vlc_runtime/ (vendored libvlc.dll, libvlccore.dll, and VLC's plugins/
# folder -- see video_player.py's module docstring) alongside the exe so video
# playback works on machines that don't have VLC installed.

import os

block_cipher = None
here = SPECPATH  # provided by PyInstaller's spec exec environment -- .../RML_PYTHON_TOOLS/patient_manager

# here/.. holds the shared cross-tool utilities (ui_widgets.py, runtype.py);
# here/tests holds the per-modality "test" tools launched by bare module name
# via analysis_registry.py -- both need to be on the analysis path, matching the
# sys.path bootstrap at the top of patient_manager_ui.py itself.
_root = os.path.dirname(here)
_tests = os.path.join(here, 'tests')

# onedir build: vlc_runtime (~136 MB) sits next to the exe permanently instead of
# being re-extracted to a temp dir on every launch (which --onefile would do).
# It now lives in tests/ alongside video_player.py, not directly under here.
a = Analysis(
    ['patient_manager_ui.py'],
    pathex=[here, _root, _tests],
    binaries=[],
    datas=[
        (os.path.join(_tests, 'vlc_runtime'), 'vlc_runtime'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RML_Clinical_Tools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep a console (equivalent to running via python.exe, not pythonw.exe) --
    # ReformatAnalogForTheia's disambiguation prompts use plain input() and need one.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RML_Clinical_Tools',
)
