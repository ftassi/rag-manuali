SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
APP := $(BIN)/manuali-rag
HOST ?= 0.0.0.0
PORT ?= 8000
FORCE_FLAG := $(if $(filter 1 true yes,$(FORCE)),--force,)
OLLAMA_MODEL ?= llama3.2:3b
OLLAMA_EMBEDDING_MODEL ?= nomic-embed-text-v2-moe
BENCHMARK_OUTPUT ?= benchmark-results/llama3.2-3b.json
RAG_EVAL_OUTPUT ?= benchmark-results/rag-model-comparison.json
RAG_EVAL_MODELS ?= llama3.2:3b qwen2.5:1.5b
EMBEDDING_EVAL_OUTPUT ?= benchmark-results/embedding-comparison.json
HYBRID_EVAL_OUTPUT ?= benchmark-results/hybrid-retrieval-comparison.json
E2E_EVAL_OUTPUT ?= benchmark-results/end-to-end-v2-llama3.2.json
INGESTION_EVAL_OUTPUT ?= benchmark-results/ingestion-synthetic.json
HTTP_SMOKE_OUTPUT ?= benchmark-results/http-smoke.json
UI_SMOKE_OUTPUT ?= benchmark-results/ui-smoke.json
UI_SMOKE_SCREENSHOT ?= benchmark-results/ui-smoke.png
REGRESSION_DIR ?= benchmark-results/regression

.PHONY: help init ollama-check benchmark rag-eval embedding-eval hybrid-eval e2e-eval ingestion-eval smoke-http smoke-ui regression regression-check start start-dev serve test lint check format ingest search ask documents health

help: ## Mostra i comandi disponibili
	@awk 'BEGIN {FS = ":.*## "; printf "Uso: make <target>\n\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: ## Crea il virtualenv, installa dipendenze e prepara .env
	@test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	@"$(BIN)/pip" install --upgrade pip
	@"$(BIN)/pip" install -e '.[dev]'
	@if [[ ! -f .env ]]; then cp .env.example .env; echo "Creato .env da .env.example"; else echo ".env già presente: non modificato"; fi
	@echo "Inizializzazione completata. Configura i modelli in .env, poi esegui: make start"

ollama-check: ## Verifica servizio e modello Ollama configurato
	@command -v ollama >/dev/null || { echo "Ollama non installato"; exit 1; }
	@ollama list | grep -Fq "$(OLLAMA_MODEL)" || { echo "Modello $(OLLAMA_MODEL) non disponibile"; exit 1; }
	@ollama list | grep -Fq "$(OLLAMA_EMBEDDING_MODEL)" || { echo "Modello $(OLLAMA_EMBEDDING_MODEL) non disponibile"; exit 1; }
	@curl --fail --silent --show-error http://127.0.0.1:11434/api/version
	@echo

benchmark: ## Esegue benchmark Ollama e salva il risultato JSON
	@mkdir -p "$(dir $(BENCHMARK_OUTPUT))"
	@$(PYTHON) scripts/benchmark_ollama.py --model "$(OLLAMA_MODEL)" --output "$(BENCHMARK_OUTPUT)"

rag-eval: ## Confronta i modelli su un corpus RAG sintetico
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@mkdir -p "$(dir $(RAG_EVAL_OUTPUT))"
	@"$(BIN)/python" scripts/evaluate_rag_models.py --models $(RAG_EVAL_MODELS) --output "$(RAG_EVAL_OUTPUT)"

embedding-eval: ## Confronta embedding hash e Ollama su query parafrasate
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@mkdir -p "$(dir $(EMBEDDING_EVAL_OUTPUT))"
	@"$(BIN)/python" scripts/evaluate_embeddings.py --output "$(EMBEDDING_EVAL_OUTPUT)"

hybrid-eval: ## Valuta e calibra il retrieval ibrido RRF
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@mkdir -p "$(dir $(HYBRID_EVAL_OUTPUT))"
	@"$(BIN)/python" scripts/evaluate_hybrid_retrieval.py --output "$(HYBRID_EVAL_OUTPUT)"

e2e-eval: ## Valuta retrieval e risposta senza limitare il documento
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@mkdir -p "$(dir $(E2E_EVAL_OUTPUT))"
	@"$(BIN)/python" scripts/evaluate_end_to_end.py --output "$(E2E_EVAL_OUTPUT)"

ingestion-eval: ## Prova importazione, ricerca e risposta su un Markdown sintetico
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@mkdir -p "$(dir $(INGESTION_EVAL_OUTPUT))"
	@"$(BIN)/python" scripts/evaluate_ingestion.py --output "$(INGESTION_EVAL_OUTPUT)"

smoke-http: ## Prova API HTTP, upload e domanda con dati sintetici temporanei
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@mkdir -p "$(dir $(HTTP_SMOKE_OUTPUT))"
	@"$(BIN)/python" scripts/smoke_http.py --output "$(HTTP_SMOKE_OUTPUT)"

smoke-ui: ## Collauda l'interfaccia con Firefox e dati sintetici temporanei
	@test -x "$(BIN)/python" || { echo "Ambiente non inizializzato: esegui make init"; exit 1; }
	@command -v firefox >/dev/null || { echo "Firefox non installato"; exit 1; }
	@mkdir -p "$(dir $(UI_SMOKE_OUTPUT))" "$(dir $(UI_SMOKE_SCREENSHOT))"
	@"$(BIN)/python" scripts/smoke_ui.py --output "$(UI_SMOKE_OUTPUT)" --screenshot "$(UI_SMOKE_SCREENSHOT)"

regression: check ollama-check ## Esegue la regressione completa sul Raspberry
	@mkdir -p "$(REGRESSION_DIR)"
	@"$(BIN)/python" scripts/evaluate_embeddings.py --output "$(REGRESSION_DIR)/embedding.json" >/dev/null
	@"$(BIN)/python" scripts/evaluate_hybrid_retrieval.py --output "$(REGRESSION_DIR)/hybrid.json" >/dev/null
	@"$(BIN)/python" scripts/evaluate_end_to_end.py --output "$(REGRESSION_DIR)/end-to-end.json" >/dev/null
	@"$(BIN)/python" scripts/evaluate_ingestion.py --output "$(REGRESSION_DIR)/ingestion.json" >/dev/null
	@"$(BIN)/python" scripts/smoke_http.py --output "$(REGRESSION_DIR)/http-smoke.json" >/dev/null
	@"$(BIN)/python" scripts/smoke_ui.py --output "$(REGRESSION_DIR)/ui-smoke.json" --screenshot "$(REGRESSION_DIR)/ui-smoke.png" >/dev/null
	@"$(BIN)/python" scripts/check_regression.py "$(REGRESSION_DIR)"

regression-check: ## Verifica le soglie sugli ultimi report di regressione
	@"$(BIN)/python" scripts/check_regression.py "$(REGRESSION_DIR)"

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
