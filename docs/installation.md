# Installation Guide

This guide covers all installation methods for dazzlesum across different platforms.

## System Requirements

- **Python**: 3.9 or higher
- **Operating System**: Windows, macOS, Linux, BSD
- **Dependencies** (pip package): `dazzle-lib` and `dazzle-filekit`, installed automatically by pip; filekit's UNC-aware path layer is backed by [`unctools`](https://github.com/djdarcy/UNCtools)
- **Dependencies** (single-file `dazzlesum.py`): none -- the stitched artifact runs on the standard library alone

## Installation Methods

### Install from PyPI (Recommended)

The simplest way to install dazzlesum:

```bash
pip install dazzlesum
```

After installation, the `dazzlesum` command will be available globally:

```bash
dazzlesum --help
```

### Install from Source

For the latest development version:

```bash
git clone https://github.com/djdarcy/dazzlesum.git
cd dazzlesum
pip install -e .
```

This installs in "editable" mode, so changes to the source code take effect immediately.

### Download Single File

For portable use without installation -- the single file is generated from the `src/` package at build time and is fully self-contained (standard library only, no dependencies):

```bash
# Download the script
curl -O https://raw.githubusercontent.com/djdarcy/dazzlesum/main/dazzlesum.py

# Make executable (Unix/Linux/macOS)
chmod +x dazzlesum.py

# Run directly
python dazzlesum.py --help
```

## Platform-Specific Instructions

### Windows

#### Standard Installation
```cmd
pip install dazzlesum
```

#### With UNC Path Support
For enhanced Windows UNC path handling:
```cmd
pip install dazzlesum[windows]
```

Or if installing from source:
```cmd
pip install -e ".[windows]"
```

#### Using Command Prompt
```cmd
REM Install globally
pip install dazzlesum

REM Or run directly
python dazzlesum.py
```

#### Using PowerShell
```powershell
# Install with PowerShell
pip install dazzlesum

# Run with full path if needed
python C:\path\to\dazzlesum.py
```

### macOS

#### Using Homebrew Python
```bash
# Install with Homebrew's Python
/opt/homebrew/bin/pip3 install dazzlesum

# Or use system Python
pip3 install dazzlesum
```

#### Using pyenv
```bash
# With pyenv
pyenv install 3.11.0
pyenv global 3.11.0
pip install dazzlesum
```

### Linux

#### Ubuntu/Debian
```bash
# Update package list
sudo apt update

# Install Python pip if needed
sudo apt install python3-pip

# Install dazzlesum
pip3 install dazzlesum
```

#### CentOS/RHEL/Fedora
```bash
# Install Python pip if needed
sudo dnf install python3-pip  # Fedora
# sudo yum install python3-pip  # CentOS/RHEL

# Install dazzlesum
pip3 install dazzlesum
```

#### Arch Linux
```bash
# Install pip if needed
sudo pacman -S python-pip

# Install dazzlesum
pip install dazzlesum
```

### BSD Systems

#### FreeBSD
```bash
# Install Python and pip
sudo pkg install python3 py39-pip

# Install dazzlesum
pip install dazzlesum
```

## Development Installation

### For Contributors

```bash
# Clone the repository
git clone https://github.com/djdarcy/dazzlesum.git
cd dazzlesum

# Install with development dependencies
pip install -e ".[dev]"
```

This includes additional tools for development:
- `pytest` for testing
- `black` for code formatting
- `flake8` for linting
- `mypy` for type checking

### Running Tests

```bash
# Install with test dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=dazzlesum
```

## Virtual Environment Setup

### Using venv

```bash
# Create virtual environment
python -m venv dazzlesum-env

# Activate (Linux/macOS)
source dazzlesum-env/bin/activate

# Activate (Windows)
dazzlesum-env\Scripts\activate

# Install dazzlesum
pip install dazzlesum
```

### Using conda

```bash
# Create conda environment
conda create -n dazzlesum python=3.11

# Activate environment
conda activate dazzlesum

# Install dazzlesum
pip install dazzlesum
```

## Verification

### Test Installation

```bash
# Check version
dazzlesum --version

# Show help
dazzlesum --help

# Test basic functionality
dazzlesum --dry-run
```

### Test Cross-Platform Features

```bash
# Test with different algorithms
dazzlesum --algorithm sha512 --help

# Test management operations
dazzlesum --manage list --help
```

## Troubleshooting

### Common Issues

#### "dazzlesum command not found"

**Solution**: Ensure pip install location is in PATH:

```bash
# Find pip install location
python -m site --user-base

# Add to PATH (add to ~/.bashrc or ~/.zshrc)
export PATH="$PATH:$(python -m site --user-base)/bin"
```

#### Permission Errors on Unix

**Solution**: Use user installation:

```bash
pip install --user dazzlesum
```

#### Python Version Issues

**Solution**: Check Python version:

```bash
python --version
# Should be 3.7 or higher

# Use specific Python version
python3.11 -m pip install dazzlesum
```

### Windows-Specific Issues

#### UNC Path Problems

**Solution**: Install with Windows extras:

```cmd
pip install dazzlesum[windows]
```

#### Command Prompt vs PowerShell

Both should work identically. If issues occur:

```cmd
REM Use full Python path
C:\Python311\python.exe -m dazzlesum
```

### Network Installation

For systems without internet access:

```bash
# Download wheel on connected system
pip download dazzlesum

# Transfer wheel file and install offline
pip install dazzlesum-*.whl
```

## Updating

### Update from PyPI
```bash
pip install --upgrade dazzlesum
```

### Update from Source
```bash
cd dazzlesum
git pull origin main
pip install -e .
```

## Uninstallation

```bash
pip uninstall dazzlesum
```

This removes the package but preserves any `.shasum` files you've created.