app:
	pyinstaller ./ephyr.spec --noconfirm

# pypi
build-main:
	python -m build --outdir=./dist/main

build-test:
	python -m build --outdir=./dist/test

publish-main:
	twine upload dist/main/*

publish-test:
	twine upload -r testpypi dist/test/*

build-docs:
	mkdocs build --strict

local-docs:
	mkdocs serve
