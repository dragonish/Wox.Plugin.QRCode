.PHONY: help init check-init check-dev-deps install clean lint format build test package

DIST_DIR := dist
SRC_DIR := src

ifeq ($(OS),Windows_NT)
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -ExecutionPolicy Bypass -Command
PYTHON ?= python
else
PYTHON ?= python3
endif

help:
	@echo "Available commands:"
	@echo "  make init    - Initialize template values interactively"
	@echo "  make install  - Install project dependencies"
	@echo "  make clean   - Clean build directory"
	@echo "  make build   - Build project"
	@echo "  make package - Build plugin package"

init:
	$(PYTHON) scripts/init-wox-project.py

check-init:
	@$(PYTHON) scripts/init-wox-project.py --check-initialized

check-dev-deps:
	@uv run python -c "import importlib.util, sys; missing = [name for name in ('ruff', 'mypy') if importlib.util.find_spec(name) is None]; missing and (print('Development dependencies are not installed. Run make install first.', file=sys.stderr), print('Missing packages: ' + ', '.join(missing), file=sys.stderr), sys.exit(1))"

install: check-init
	uv sync --all-extras

lint: check-init check-dev-deps
	uv run ruff check src tests
	uv run mypy src tests

format: check-init check-dev-deps
	uv run ruff format src tests

test: check-init
	uv run python -m unittest tests/test_qrcode.py tests/test_query.py

clean:
ifeq ($(OS),Windows_NT)
	if (Test-Path '$(DIST_DIR)') { Remove-Item -Recurse -Force '$(DIST_DIR)' }
	if (Test-Path 'build') { Remove-Item -Recurse -Force 'build' }
else
	rm -rf $(DIST_DIR)
	rm -rf build
endif

build: lint format
ifeq ($(OS),Windows_NT)
	if (Test-Path '$(DIST_DIR)') { Remove-Item -Recurse -Force '$(DIST_DIR)' }
	$(PYTHON) scripts/build_dependencies.py
	Copy-Item '$(SRC_DIR)\*' -Destination '$(DIST_DIR)' -Recurse -Force
	if (Test-Path '$(DIST_DIR)\__pycache__') { Remove-Item -Recurse -Force '$(DIST_DIR)\__pycache__' }
	Set-Content -Path '$(DIST_DIR)\__init__.py' -Encoding ascii -Value @('import os','import sys','','# Add dependencies directory to Python path','deps_dir = os.path.join(os.path.dirname(__file__), "dependencies")','if deps_dir not in sys.path:','    sys.path.insert(0, deps_dir)','','from .qrcode_main import plugin','','__all__ = ["plugin"]')
	Copy-Item 'plugin.json' -Destination '$(DIST_DIR)\plugin.json' -Force
	New-Item -ItemType Directory -Force -Path '$(DIST_DIR)\images' | Out-Null
	Copy-Item 'images\*' -Destination '$(DIST_DIR)\images' -Recurse -Force
else
	rm -rf $(DIST_DIR)
	$(PYTHON) scripts/build_dependencies.py
	cp -r $(SRC_DIR)/* $(DIST_DIR)/
	rm -rf $(DIST_DIR)/__pycache__
	printf '%s\n' 'import os' 'import sys' '' '# Add dependencies directory to Python path' 'deps_dir = os.path.join(os.path.dirname(__file__), "dependencies")' 'if deps_dir not in sys.path:' '    sys.path.insert(0, deps_dir)' '' 'from .qrcode_main import plugin' '' '__all__ = ["plugin"]' > $(DIST_DIR)/__init__.py
	cp plugin.json $(DIST_DIR)/plugin.json
	mkdir -p $(DIST_DIR)/images
	cp images/* $(DIST_DIR)/images/
endif

package: check-init build
	$(PYTHON) scripts/package.py
ifeq ($(OS),Windows_NT)
	if (Test-Path '$(DIST_DIR)') { Remove-Item -Recurse -Force '$(DIST_DIR)' }
else
	rm -rf $(DIST_DIR)
endif
