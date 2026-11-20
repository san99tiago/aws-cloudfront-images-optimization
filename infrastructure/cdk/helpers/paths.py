"""Absolute paths to the non-CDK folders of the repository (Lambda code, layers, CloudFront Functions, assets)."""

# Built-in imports
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

PATH_TO_LAMBDAS = REPO_ROOT / "backend" / "lambdas"
PATH_TO_IMAGE_OPTIMIZER = PATH_TO_LAMBDAS / "image_optimizer"
PATH_TO_PROFILE_API = PATH_TO_LAMBDAS / "profile_api"
PATH_TO_USERS_SEEDER = PATH_TO_LAMBDAS / "users_seeder"

PATH_TO_PILLOW_LAYER = REPO_ROOT / "lambda-layers" / "pillow" / "modules"

PATH_TO_CLOUDFRONT_FUNCTIONS = REPO_ROOT / "cloudfront"
PATH_TO_IMAGE_NEGOTIATION_FUNCTION = PATH_TO_CLOUDFRONT_FUNCTIONS / "image-negotiation.js"
PATH_TO_SPA_REWRITE_FUNCTION = PATH_TO_CLOUDFRONT_FUNCTIONS / "spa-rewrite.js"

PATH_TO_ORIGINAL_IMAGES = REPO_ROOT / "assets" / "images" / "original"
PATH_TO_FRONTEND_BUILD = REPO_ROOT / "frontend" / "dist"
