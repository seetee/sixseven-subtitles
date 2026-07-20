PREFIX  ?= $(HOME)/.local
THEMES  := $(HOME)/.config/caption/themes.toml
MENU    := $(HOME)/.local/share/kio/servicemenus/add-captions.desktop

.PHONY: install uninstall test check

## install: put caption on PATH and register the Dolphin right-click menu
install:
	@command -v ffmpeg >/dev/null || { echo "caption: ffmpeg is not installed — do that first."; exit 1; }
	install -Dm755 caption $(PREFIX)/bin/caption
	install -Dm755 add-captions.desktop $(MENU)
# Never clobber an installed themes.toml: it's a config file you may have added
# your own themes to. New shipped themes have to be merged in by hand.
	@if [ -f $(THEMES) ]; then \
		echo "keeping your existing $(THEMES)"; \
		diff -q themes.toml $(THEMES) >/dev/null 2>&1 || \
			echo "  (it differs from the repo copy — 'diff themes.toml $(THEMES)' to see how)"; \
	else \
		install -Dm644 themes.toml $(THEMES); \
		echo "installed $(THEMES)"; \
	fi
	@command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 2>/dev/null || true
	@echo
	@echo "Done. caption is on PATH; right-click a .webm in Dolphin -> Captions."
	@command -v caption >/dev/null || echo "NOTE: $(PREFIX)/bin is not on your PATH — add it to use 'caption' by name."

## uninstall: remove everything except your themes.toml and the model cache
uninstall:
	rm -f $(PREFIX)/bin/caption $(MENU)
	@command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 2>/dev/null || true
	@echo "Removed. Left alone: $(THEMES), ~/.cache/caption-models, ~/.venvs/caption"

## test: run the test suite (no ML dependencies needed)
test check:
	python3 test_caption.py
