PYTHON ?= .venv/bin/python
.PHONY: install run test lint predict eval index train bench smoke
install:
	uv venv --python 3.11 .venv
	uv pip sync --python $(PYTHON) requirements.lock
run:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000
test:
	$(PYTHON) -m pytest
lint:
	.venv/bin/ruff check .
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
