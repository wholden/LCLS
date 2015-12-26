#from distutils.core import setup

import sys
import pip

from setuptools import setup, find_packages

pip.main(['install', '--user',  'pyzmq', '--install-option=--zmq=bundled'])

setup(name='dataccess',
    version='1.0',
    packages = find_packages('.'),
    package_dir={'dataccess': 'dataccess'},
    package_data={'dataccess': ['data/*']},
    scripts = [
        'scripts/mecana.py', 'scripts/logbooksync.py'
    ],
    install_requires = ['google-api-python-client', 'httplib2', 'atomicfile', 'urllib3', 'gspread', 'requests', 'multiprocess', 'dill', 'pox', 'ppft', 'ipdb'],
    zip_safe = False,
    )

pip.main(['install', '--user', 'git+https://github.com/uqfoundation/pathos.git'])

print  "Packages are: ", find_packages('.')
