from setuptools import setup
from distutils import util
from distutils.core import Extension
import glob


with open('requirements.txt') as f:
    requirements = f.read().splitlines()

version = '0.0.1'

extensions = [
    Extension('voiplib._voiplib.crc',
        include_dirs=[],
        library_dirs=[],
        libraries=[],
        sources=['src/crc.c'],
    ),
    Extension('voiplib._voiplib.audio',
        include_dirs=[],
        library_dirs=[],
        libraries=[],
        sources=['src/audio.c'],
    ),
]


setup(
    name='voiplib',
    version=version,
    packages=['voiplib', 'voiplib.util', 'voiplib._voiplib'],
    include_package_data=True,
    install_requires=requirements,
    ext_modules=extensions,

    data_files=[
        ('voiplib/bin', glob.glob('voiplib/bin/*'))
    ],
)
