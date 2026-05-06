.PHONY: help # print this help list
help:
	grep PHONY Makefile | sed 's/.PHONY: /make /' | grep -v grep

.PHONY: clean # remove packaging files
clean:
	find . -iname "__pycache__" | while read d; do rm -rf $$d; done

.PHONY: install # install runtime + dev deps
install:
	uv sync

.PHONY: test # run unit tests
test:
	uv run pytest

.PHONY: lint # run ruff check (no fix)
lint:
	uv run ruff check --no-fix .

.PHONY: format # run ruff format
format:
	uv run ruff format .

.PHONY: typecheck # run pyright
typecheck:
	uv run pyright

.PHONY: serve # run FastAPI dev server
serve:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

.PHONY: client # run audio client
DEVICE ?= default
SOURCE_LANG ?= it-IT
ROOM ?= 1
client:
	uv run python -m audio_client --server ws://localhost:8000 --lang $(SOURCE_LANG) --room $(ROOM) --device "$(DEVICE)"

.PHONY: major minor patch # bump version, regenerate CHANGELOG, push
major:
	$(MAKE) release PART=major
minor:
	$(MAKE) release PART=minor
patch:
	$(MAKE) release PART=patch

release:
	bump-my-version bump $(PART)
	git-cliff --config pyproject.toml --output CHANGELOG.md
	sed -i 's/<!-- [0-9]* -->//g' CHANGELOG.md
	git add CHANGELOG.md
	git commit --amend --no-edit
	git tag -f v$$(python -c "from app import __version__; print(__version__)")

.PHONY: changelog # regenerate CHANGELOG and amend it on the commit
changelog:
	git-cliff --config pyproject.toml --output CHANGELOG.md
	sed -i 's/<!-- [0-9]* -->//g' CHANGELOG.md
	git add CHANGELOG.md
	git commit --amend --no-edit
