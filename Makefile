ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
BOOTSTRAP ?= py -3.11
else
PYTHON ?= .venv/bin/python
BOOTSTRAP ?= python3.11
endif
.PHONY: install run test lint predict eval index train bench smoke acceptance
install:
	$(BOOTSTRAP) -m venv .venv
	$(PYTHON) -m pip install -r requirements.lock
run:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000
test:
	$(PYTHON) -m pytest
lint:
	$(PYTHON) -m ruff check .
predict:
	$(PYTHON) -m scripts.predict --input "$(IN)" --output "$(OUT)"
eval:
	$(PYTHON) -m scripts.eval
index:
	$(PYTHON) -m scripts.build_index
train:
	$(PYTHON) -m scripts.train_classifier
bench:
	$(PYTHON) -m scripts.bench
smoke:
	$(PYTHON) -m scripts.smoke
acceptance:
	$(PYTHON) -m scripts.acceptance
