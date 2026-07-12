.PHONY: setup test build clean

PYTHON = .venv/bin/python
PIP = .venv/bin/pip
PYINSTALLER = .venv/bin/pyinstaller

# Detect OS for path separator in PyInstaller --add-data
ifeq ($(OS),Windows_NT)
    SEP = ;
    EXE_EXT = .exe
else
    SEP = :
    EXE_EXT =
endif

setup:
	python -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install pyinstaller

test:
	$(PYTHON) -m unittest discover -s tests

build:
	$(PIP) show pyinstaller >/dev/null 2>&1 || $(PIP) install pyinstaller
	$(PYINSTALLER) --onefile \
		--add-data "cerberai/static$(SEP)cerberai/static" \
		--name "cerberai" \
		cerberai/main.py

clean:
	rm -rf build dist cerberai.spec
