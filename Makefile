SHELL := /usr/bin/env bash

RESOURCES_DIR := resources
INSTALL_SCRIPTS := $(sort $(wildcard $(RESOURCES_DIR)/install_*.sh))
.DEFAULT_GOAL := setup

.PHONY: setup install resources

setup: resources

install: setup

resources:
	@echo "[make] Executando scripts de instalacao em ordem:"
	@if [[ -z "$(INSTALL_SCRIPTS)" ]]; then \
		echo "[make][erro] Nenhum script install_*.sh encontrado em $(RESOURCES_DIR)."; \
		exit 1; \
	fi
	@for script in $(INSTALL_SCRIPTS); do \
		echo " - $$script"; \
		bash "$$script"; \
	done
