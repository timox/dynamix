# DynaMix Makefile: common tasks (use the project's virtual environment)

.PHONY: help install install-dev check gui test smoke clean

help:
	@echo "DynaMix"
	@echo "  install      Install the dependencies"
	@echo "  install-dev  Install the development dependencies"
	@echo "  check        Check the installation (check_install.py)"
	@echo "  gui          Start the GUI"
	@echo "  test         Run the unit tests"
	@echo "  smoke        Run the GUI smoke test"
	@echo "  clean        Remove caches and build files"

install:
	pip install -r requirements.txt

install-dev: install
	pip install -r requirements-dev.txt

check:
	python check_install.py

gui:
	python gui.py

test:
	python -m unittest discover -s tests

smoke:
	python tests/gui_smoke.py

clean:
	find . -path ./venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ htmlcov/
