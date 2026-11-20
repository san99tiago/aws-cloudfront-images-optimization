################################################################################
# Rufus Bank App Images Optimization: root orchestrator
################################################################################
SHELL := /bin/bash
.DEFAULT_GOAL := help

DEPLOYMENT_ENVIRONMENT ?= dev
MAIN_RESOURCES_NAME := cloudfront-images-optimization
PYTHON := $(CURDIR)/.venv/bin/python3
CDK := npx --yes aws-cdk@2.1149.0
BACKEND_STACK := $(MAIN_RESOURCES_NAME)-backend-$(DEPLOYMENT_ENVIRONMENT)

export DEPLOYMENT_ENVIRONMENT
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION := 1

.PHONY: help install install-python install-layers install-frontend build-frontend synth diff deploy \
        outputs frontend-config dev test e2e costs images destroy clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-python install-layers install-frontend ## Install everything (Poetry .venv, Lambda Layers, frontend)

install-python: ## Poetry dependencies into .venv (project root)
	poetry config virtualenvs.in-project true --local
	poetry install --no-interaction

install-layers: ## Lambda Layers (Pillow for arm64), idempotent
	@cd lambda-layers && $(MAKE) --no-print-directory install PYTHON=$(PYTHON)

install-frontend: ## Frontend npm dependencies
	cd frontend && npm ci --no-audit --no-fund

build-frontend: ## Build the React portal (frontend/dist)
	cd frontend && npm run build

images: ## Generate the 40 demo images with OpenAI (needs OPENAI_API_KEY in .env)
	$(PYTHON) scripts/generate_images.py

synth: install-layers build-frontend ## cdk synth (all stacks)
	$(CDK) synth --quiet

diff: install-layers build-frontend ## cdk diff (all stacks)
	$(CDK) diff --all

deploy: install-layers build-frontend ## Deploy all the stacks (reads DEMO_USERS_PASSWORD from .env)
	@test -f .env || (echo "ERROR: create .env from .example.env" && exit 1)
	@set -a && source ./.env && set +a && \
	  test -n "$$DEMO_USERS_PASSWORD" || (echo "ERROR: DEMO_USERS_PASSWORD is empty in .env" && exit 1); \
	  mkdir -p outputs && \
	  $(CDK) deploy --all --require-approval never \
	    --parameters "$(BACKEND_STACK):DemoUsersPassword=$$DEMO_USERS_PASSWORD" \
	    --outputs-file outputs/cdk-outputs.json
	@$(MAKE) --no-print-directory frontend-config

outputs: ## Refresh outputs/cdk-outputs.json from CloudFormation
	$(PYTHON) scripts/stack_outputs.py

frontend-config: ## Write frontend/public/config.json for local development (npm run dev)
	$(PYTHON) scripts/stack_outputs.py --frontend-config frontend/public/config.json

dev: frontend-config ## Run the portal locally against the deployed backend
	cd frontend && npm run dev

test: ## Unit tests (optimizer, CloudFront Function, CDK assertions)
	$(PYTHON) -m pytest

e2e: ## End-to-end validation against the deployed environment
	$(PYTHON) scripts/e2e_test.py

costs: ## Regenerate docs/COSTS.md (cost model 10M / 60M / 100M requests)
	$(PYTHON) scripts/cost_model.py

destroy: ## Destroy all the stacks
	$(CDK) destroy --all --force

clean: ## Remove build outputs (keeps .venv and node_modules)
	cd lambda-layers && $(MAKE) --no-print-directory clean
	rm -rf cdk.out frontend/dist
