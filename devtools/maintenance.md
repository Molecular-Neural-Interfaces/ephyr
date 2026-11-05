
# Ephyr Release and Documentation Guide

This guide describes the process of publishing a new version of the Ephyr platform, including updating the package on PyPI, maintaining the changelog, creating a GitHub release, and working with documentation.

## 📦 Project Repositories

- **Main Ephyr code**: [Molecular-Neural-Interfaces/ephyr](https://github.com/Molecular-Neural-Interfaces/ephyr)
- **Add-ons**: [Molecular-Neural-Interfaces/ephyr-add-ons](https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons)

## 🚀 Publishing Releases

Before the steps bellow install requirements:
```bash
pip install -r devtools/dev-requirements.txt
```

### 1. Updating the version

Before building, you need to change the version number in the `ephyr/version.py` file.

- **File**: [`ephyr/version.py`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/master/ephyr/version.py)
- **Action**: edit the version value according to Semantic Versioning (e.g., `1.0.12` → `1.0.13`).



### 2. Building and publishing to PyPI

To build the distribution and upload it to PyPI, run the following commands. They are also available in the project's [`Makefile`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/master/Makefile).

```bash
# Build the package
python -m build --outdir=./dist/main

# Upload to PyPI (credentials required)
twine upload dist/main/*
```

After uploading, verify that the new version appears on the project page on PyPI:  
[https://pypi.org/project/ephyr/](https://pypi.org/project/ephyr/)


### 3. Updating CHANGELOG.md

The changelog is generated automatically using the `changelog-maestro` tool based on commit history (using Conventional Commits).

- **Changelog file**: [`CHANGELOG.md`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/master/CHANGELOG.md)
- **Command**:

```bash
changelog-maestro --template devtools/changelog.md.j2
```


### 4. Creating a GitHub Release

After successfully publishing to PyPI and updating the changelog, you need to create a new release on GitHub.

- **Releases page**: [https://github.com/Molecular-Neural-Interfaces/ephyr/releases](https://github.com/Molecular-Neural-Interfaces/ephyr/releases)
- **Steps**:
  1. Click **"Draft a new release"**.
  2. Create a new tag corresponding to the version from `version.py` (e.g., `v1.0.13`).
  3. Fill in the release description (you can copy the relevant section from `CHANGELOG.md`).
  4. Publish the release.

## 📖 Documentation

The project documentation is built with MkDocs and is automatically updated when a new GitHub release is created.

- **Public documentation**: [https://ephyr.readthedocs.io/](https://ephyr.readthedocs.io/)
- **Read the Docs management**: [https://app.readthedocs.org/projects/ephyr/](https://app.readthedocs.org/projects/ephyr/)

### Local documentation check

Before publishing a release, it is recommended to check the documentation build locally.

```bash
# Strict build (error checking)
mkdocs build --strict

# Local preview (development server)
mkdocs serve
```

After running `mkdocs serve`, the documentation will be available at `http://127.0.0.1:8000`.


## ✅ Release Checklist

- [ ] Version updated in `ephyr/version.py`
- [ ] Build completed (`python -m build --outdir=./dist/main`)
- [ ] Package uploaded to PyPI (`twine upload dist/main/*`)
- [ ] New version verified on [pypi.org/project/ephyr](https://pypi.org/project/ephyr/)
- [ ] `CHANGELOG.md` updated (`changelog-maestro --template devtools/changelog.md.j2`)
- [ ] New GitHub Release created with a tag matching the version
- [ ] Documentation built locally successfully (`mkdocs build --strict`)
- [ ] Documentation automatically updated on Read the Docs after release publication


## 🔗 Useful Links

- [Main repository](https://github.com/Molecular-Neural-Interfaces/ephyr)
- [Add-ons repository](https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons)
- [Version file](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/master/ephyr/version.py)
- [Makefile](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/master/Makefile)
- [CHANGELOG.md](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/master/CHANGELOG.md)
- [GitHub Releases page](https://github.com/Molecular-Neural-Interfaces/ephyr/releases)
- [PyPI – ephyr](https://pypi.org/project/ephyr/)
- [Read the Docs – ephyr](https://ephyr.readthedocs.io/)
- [Read the Docs admin panel](https://app.readthedocs.org/projects/ephyr/)
