SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
APP := $(BIN)/manuali-rag
HOST ?= 0.0.0.0
PORT ?= 8000
FORCE_FLAG := $(if $(filter 1 true yes,$(FORCE)),--force,)
LLAMA_REPO ?= https://github.com/ggml-org/llama.cpp.git
LLAMA_DIR ?= .local/llama.cpp
LLAMA_BUILD_DIR := $(LLAMA_DIR)/build
LLAMA_SERVER := $(LLAMA_BUILD_DIR)/bin/llama-server
LLAMA_JOBS ?= $(shell nproc 2>/dev/null || echo 4)

.PHONY: help init llama-install llama-version start start-dev serve test lint check format ingest search ask documents health

help: ## Mostra i comandi disponibili
	@awk 'BEGIN {FS = ":.*## "; printf "Uso: make <target>\n\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: ## Crea il virtualenv, installa dipendenze e prepara .env
	@test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	@"$(BIN)/pip" install --upgrade pip
	@"$(BIN)/pip" install -e '.[dev]'
	@if [[ ! -f .env ]]; then cp .env.example .env; echo "Creato .env da .env.example"; else echo ".env già presente: non modificato"; fi
	@echo "Inizializzazione completata. Configura i modelli in .env, poi esegui: make start"

llama-install: ## Installa prerequisiti e compila llama.cpp localmente
	@command -v apt-get >/dev/null || { echo "Target supportato su Debian, Ubuntu e Raspberry Pi OS"; exit 1; }
	@sudo apt-get update
	@sudo apt-get install -y build-essential cmake git libcurl4-openssl-dev
	@mkdir -p "$(dir $(LLAMA_DIR))"
	@if [[ -d "$(LLAMA_DIR)/.git" ]]; then \
		git -C "$(LLAMA_DIR)" pull --ff-only; \
	elif [[ -e "$(LLAMA_DIR)" ]]; then \
		echo "$(LLAMA_DIR) esiste ma non è un clone Git: rinominala o rimuovila"; exit 1; \
	else \
		git clone --depth 1 "$(LLAMA_REPO)" "$(LLAMA_DIR)"; \
	fi
	@cmake -S "$(LLAMA_DIR)" -B "$(LLAMA_BUILD_DIR)" -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON
	@cmake --build "$(LLAMA_BUILD_DIR)" --config Release --target llama-server llama-cli --parallel "$(LLAMA_JOBS)"
	@"$(LLAMA_SERVER)" --version

llama-version: ## Mostra la versione locale di llama.cpp
	@test -x "$(LLAMA_SERVER)" || { echo "llama.cpp non installato: esegui make llama-install"; exit 1; }
	@"$(LLAMA_SERVER)" --version

start: ## Avvia API e interfaccia web
	@test -x "$(APP)" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@"$(APP)" serve --host "$(HOST)" --port "$(PORT)"

start-dev: ## Avvia senza embedding semantico, per una prova rapida
	@test -x "$(APP)" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@MANUALI_EMBEDDING_PROVIDER=hash MANUALI_CAPTION_MODE=off "$(APP)" serve --host "$(HOST)" --port "$(PORT)"

serve: start ## Alias di start

test: ## Esegue la suite automatica
	@test -x "$(BIN)/pytest" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@"$(BIN)/pytest" -q

lint: ## Controlla stile e problemi statici
	@test -x "$(BIN)/ruff" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@"$(BIN)/ruff" check .

check: lint test ## Esegue lint e test

format: ## Formatta il codice Python
	@test -x "$(BIN)/ruff" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@"$(BIN)/ruff" check . --fix
	@"$(BIN)/ruff" format .

ingest: ## Indicizza FILE=/percorso/manuale.pdf
	@test -n "$(FILE)" || { echo "Uso: make ingest FILE=/percorso/manuale.pdf"; exit 1; }
	@"$(APP)" ingest "$(FILE)" $(FORCE_FLAG)

search: ## Cerca fonti: make search QUESTION="codice E104"
	@test -n "$(QUESTION)" || { echo 'Uso: make search QUESTION="codice E104"'; exit 1; }
	@"$(APP)" search "$(QUESTION)"

ask: ## Fa una domanda: make ask QUESTION="Come pulisco il filtro?"
	@test -n "$(QUESTION)" || { echo 'Uso: make ask QUESTION="Come pulisco il filtro?"'; exit 1; }
	@"$(APP)" ask "$(QUESTION)"

documents: ## Elenca i manuali indicizzati
	@"$(APP)" documents

health: ## Controlla l'API in esecuzione
	@curl --fail --silent --show-error "http://127.0.0.1:$(PORT)/api/health"
	@echo
