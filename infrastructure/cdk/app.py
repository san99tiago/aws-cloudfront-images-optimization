#!/usr/bin/env python3

# Built-in imports
import os

# External imports
import aws_cdk as cdk

# Own imports
from helpers.add_tags import add_tags_to_app
from stacks.cdk_backend_stack import BackendStack
from stacks.cdk_frontend_stack import FrontendStack
from stacks.cdk_images_stack import ImagesStack

print("--> Deployment AWS configuration (safety first):")
print("CDK_DEFAULT_ACCOUNT", os.environ.get("CDK_DEFAULT_ACCOUNT"))
print("CDK_DEFAULT_REGION", os.environ.get("CDK_DEFAULT_REGION"))

app: cdk.App = cdk.App()

# Configurations for the deployment (obtained from env vars and CDK context)
DEPLOYMENT_ENVIRONMENT = os.environ.get("DEPLOYMENT_ENVIRONMENT", "dev")
MAIN_RESOURCES_NAME = app.node.try_get_context("app_config")[DEPLOYMENT_ENVIRONMENT]["main_resources_name"]
APP_CONFIG = app.node.try_get_context("app_config")[DEPLOYMENT_ENVIRONMENT]

# CloudFront scoped resources (AWS WAF web ACLs, log delivery sources, metrics) live in us-east-1
REGION = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")
if REGION != "us-east-1":
    raise RuntimeError("Deploy this project in us-east-1 (AWS WAF for CloudFront and CloudFront logs delivery)")

ENV = {"account": os.environ.get("CDK_DEFAULT_ACCOUNT"), "region": REGION}

# STACK 1: Images (ORIGINAL + OPTIMIZED buckets, optimizer Lambda, catalog, images CDN)
images_stack = ImagesStack(
    app,
    f"{MAIN_RESOURCES_NAME}-images-{DEPLOYMENT_ENVIRONMENT}",
    MAIN_RESOURCES_NAME,
    APP_CONFIG,
    env=ENV,
    description=f"Stack for {MAIN_RESOURCES_NAME} images pipeline and CDN in {DEPLOYMENT_ENVIRONMENT} environment",
)

# STACK 2: Backend (Cognito, users profiles, profile API)
backend_stack = BackendStack(
    app,
    f"{MAIN_RESOURCES_NAME}-backend-{DEPLOYMENT_ENVIRONMENT}",
    MAIN_RESOURCES_NAME,
    APP_CONFIG,
    catalog_table=images_stack.catalog_table,
    images_cdn_url=f"https://{images_stack.images_domain_name}",
    env=ENV,
    description=f"Stack for {MAIN_RESOURCES_NAME} backend (auth and API) in {DEPLOYMENT_ENVIRONMENT} environment",
)

# STACK 3: Frontend (React portal on S3 + CloudFront)
frontend_stack = FrontendStack(
    app,
    f"{MAIN_RESOURCES_NAME}-frontend-{DEPLOYMENT_ENVIRONMENT}",
    MAIN_RESOURCES_NAME,
    APP_CONFIG,
    user_pool_id=backend_stack.user_pool.user_pool_id,
    user_pool_client_id=backend_stack.user_pool_client.user_pool_client_id,
    http_api_domain=backend_stack.http_api_domain,
    images_cdn_domain=images_stack.images_domain_name,
    env=ENV,
    description=f"Stack for {MAIN_RESOURCES_NAME} frontend portal in {DEPLOYMENT_ENVIRONMENT} environment",
)
backend_stack.add_stack_dependency(images_stack)
frontend_stack.add_stack_dependency(backend_stack)

# Apply global tags
add_tags_to_app(app, MAIN_RESOURCES_NAME, DEPLOYMENT_ENVIRONMENT)

app.synth()
