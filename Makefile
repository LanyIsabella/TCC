SHELL := /usr/bin/env bash

RESOURCES_DIR := resources
INSTALL_SCRIPTS := $(sort $(wildcard $(RESOURCES_DIR)/install_*.sh))

.PHONY: setup scripts run

setup:
	@echo "[make] Executando scripts de instalacao em ordem:"
	@for script in $(INSTALL_SCRIPTS); do \
		echo " - $$script"; \
		bash "$$script"; \
	done

scripts:
	@echo "[make] Scripts encontrados em $(RESOURCES_DIR):"
	@for script in $(INSTALL_SCRIPTS); do \
		echo " - $$script"; \
	done

run:
	@if [[ -z "$(script)" ]]; then \
		echo "Uso: make run script=resources/install_uv.sh"; \
		exit 1; \
	fi
	@bash "$(script)"
