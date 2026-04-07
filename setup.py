#!/usr/bin/env python3
from setuptools import setup
import os

# Read version from dazzlesum.py

def get_version():
    with open('dazzlesum.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
        # Extract MAJOR, MINOR, PATCH for PEP 440 compliant version
        for line in content.splitlines():
            if line.strip().startswith('MAJOR, MINOR, PATCH ='):
                # Extract the numbers from "MAJOR, MINOR, PATCH = 1, 3, 2"
                parts = line.split('=')[1].strip().split(',')
                try:
                    major = int(parts[0].strip())
                    minor = int(parts[1].strip())
                    patch = int(parts[2].strip())
                    return f"{major}.{minor}.{patch}"
                except (ValueError, IndexError):
                    break
        
        # Fallback: extract base version from __version__ if MAJOR,MINOR,PATCH not found
        for line in content.splitlines():
            if line.strip().startswith('__version__'):
                version = line.split('=')[1].strip().strip('"\'')
                # Extract base version if it contains build info
                if '_' in version:
                    return version.split('_')[0]
                return version
                
    return '1.1.0'

# Read long description from README

def get_long_description():
    if os.path.exists('README.md'):
        with open('README.md', 'r', encoding='utf-8') as f:
            return f.read()
    return 'A cross-platform file checksum utility with DOS compatibility and advanced verification features.'

setup(
    name="dazzlesum",
    version=get_version(),
    description="A cross-platform file checksum utility with DOS compatibility and advanced verification features",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Dustin Darcy",
    author_email="6962246+djdarcy@users.noreply.github.com",
    url="https://github.com/djdarcy/dazzlesum",
    py_modules=["dazzlesum"],
    entry_points={
        "console_scripts": [
            "dazzlesum=dazzlesum:main",
        ],
    },
    install_requires=[
        # Core dependencies - none required, pure Python stdlib
    ],
    extras_require={
        'windows': [
            # Enhanced Windows UNC path support
            # 'git+https://github.com/djdarcy/UNCtools.git',
        ],
        'dev': [
            'pytest>=7.0.0',
            'black>=23.0.0;python_version>="3.8"',
            'black==23.3.0;python_version=="3.7"',  # Last version supporting Python 3.7
            'flake8>=5.0.0;python_version=="3.7"',  # Max version for Python 3.7
            'flake8>=6.0.0;python_version>="3.8"',
            'mypy>=1.0.0',
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Archiving",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    keywords="checksum hash verification sha256 cross-platform dos-compatible",
    python_requires=">=3.7",
    project_urls={
        "Bug Reports": "https://github.com/djdarcy/dazzlesum/issues",
        "Source": "https://github.com/djdarcy/dazzlesum",
        "Documentation": "https://github.com/djdarcy/dazzlesum#readme",
    },
)
