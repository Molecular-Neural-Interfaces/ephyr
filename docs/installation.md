# Installation

## .exe installation

Coming soon.

## Python installation

Ephyr requires **Python 3.11 or 3.12**.

Install the package from [PyPI](https://pypi.org/project/ephyr/) into an isolated environment.

### Conda

```bash
conda deactivate
conda remove --name ephyr_env --all
conda create --name ephyr_env python=3.12 --no-default-packages
conda activate ephyr_env
pip install ephyr
```

### Venv

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install ephyr
```

### Poetry

```bash
poetry new my-project
cd my-project
poetry add ephyr
poetry install
```

### UV

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install ephyr
```

## Launch

Start the desktop application:

```bash
ephyr
```

The `ephyr` console command launches the GUI entry point. Use the same Python environment for scripts that
import Ephyr APIs (see [Analysis](analysis.md)).

## Change Python version

Ephyr supports **3.11** and **3.12**. Recreate the environment after switching — do not reuse an old venv/conda env built with another Python.

### Install another Python (OS)

**Windows**

1. Download the installer from [python.org](https://www.python.org/downloads/windows/).
2. During setup, enable **Add python.exe to PATH**.
3. Check available versions:

```powershell
py -0p
```

Use a specific version when creating an environment, for example `py -3.12`.

**macOS**

```bash
# Homebrew
brew install python@3.12

# Or pyenv
brew install pyenv
pyenv install 3.12.10
pyenv local 3.12.10
```

**Linux**

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install python3.12 python3.12-venv

# Fedora
sudo dnf install python3.12

# Or pyenv (any distro)
curl https://pyenv.run | bash
pyenv install 3.12.10
pyenv local 3.12.10
```

Then recreate the environment as described in [Python installation](#python-installation).
