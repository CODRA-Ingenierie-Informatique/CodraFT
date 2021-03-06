# -*- mode: python ; coding: utf-8 -*-


block_cipher = None

import sys
sitepackages = os.path.join(sys.prefix, 'Lib', 'site-packages')
guidata_images = os.path.join(sitepackages, 'guidata', 'images')
guidata_locale = os.path.join(sitepackages, 'guidata', 'locale', 'fr', 'LC_MESSAGES')
guiqwt_images = os.path.join(sitepackages, 'guiqwt', 'images')
guiqwt_locale = os.path.join(sitepackages, 'guiqwt', 'locale', 'fr', 'LC_MESSAGES')

a = Analysis(['codraft\\start.pyw'],
             pathex=[],
             binaries=[],
             datas=[
                    (guidata_images, 'guidata\\images'),
                    (guidata_locale, 'guidata\\locale\\fr\\LC_MESSAGES'),
                    (guiqwt_images, 'guiqwt\\images'),
                    (guiqwt_locale, 'guiqwt\\locale\\fr\\LC_MESSAGES'),
                    ('codraft\\data', 'codraft\\data'),
                    ('codraft\\locale\\fr\\LC_MESSAGES\\codraft.mo', 'codraft\\locale\\fr\\LC_MESSAGES'),
                    ],
             hiddenimports=[],
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='CodraFT',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False,
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None , icon='resources\\codraft.ico')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='CodraFT')
