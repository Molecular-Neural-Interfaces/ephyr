import sys

from setuptools import setup


gui_entrypoint = 'weegit/gui/entrypoint.py'

if "py2app" in sys.argv:
    extra_options = dict(
        name='weegit',
        setup_requires=['py2app'],
        app=[gui_entrypoint],
        options=dict(py2app=dict(argv_emulation=False, site_packages=True,
                                 plist={'CFBundleName': 'weegit'})),
    )

elif "py2exe" in sys.argv:
    extra_options = dict(
        name='weegit',
        setup_requires=['py2exe'],
        app=[gui_entrypoint],
    )

elif "py2linux" in sys.argv:  # fixme
    extra_options = dict(
        scripts=[gui_entrypoint],
    )
else:
    extra_options = {}

setup(
    **extra_options
)
