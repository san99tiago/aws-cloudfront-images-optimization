#!/usr/bin/env python3
"""
Read the CloudFormation outputs of the 3 stacks into outputs/cdk-outputs.json, and optionally write the
frontend runtime config for local development (frontend/public/config.json + frontend/.env.local).

Usage:
    python scripts/stack_outputs.py
    python scripts/stack_outputs.py --frontend-config frontend/public/config.json
"""

# Built-in imports
import argparse
import json
import os
import sys
from pathlib import Path

# External imports
import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_RESOURCES_NAME = "cloudfront-images-optimization"


def read_outputs(environment: str, region: str) -> dict[str, dict[str, str]]:
    cloudformation = boto3.client("cloudformation", region_name=region)
    outputs: dict[str, dict[str, str]] = {}
    for purpose in ("images", "backend", "frontend"):
        stack_name = f"{MAIN_RESOURCES_NAME}-{purpose}-{environment}"
        try:
            stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
        except cloudformation.exceptions.ClientError:
            continue
        outputs[stack_name] = {
            item["OutputKey"]: item["OutputValue"]
            for item in stack.get("Outputs", [])
            if not item["OutputKey"].startswith("ExportsOutput")
        }
    return outputs


def flat(outputs: dict[str, dict[str, str]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for values in outputs.values():
        merged.update(values)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frontend-config", help="path of the config.json to write for local development")
    parser.add_argument("--environment", default=os.environ.get("DEPLOYMENT_ENVIRONMENT", "dev"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()

    outputs = read_outputs(args.environment, args.region)
    if not outputs:
        print("No stacks found: deploy first (make deploy)", file=sys.stderr)
        return 1
    target = REPO_ROOT / "outputs" / "cdk-outputs.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(outputs, indent=2) + "\n", encoding="utf-8")
    print(f"--> wrote {target.relative_to(REPO_ROOT)}")

    if args.frontend_config:
        values = flat(outputs)
        cdk_context = json.loads((REPO_ROOT / "cdk.json").read_text(encoding="utf-8"))["context"]
        app_config = cdk_context["app_config"][args.environment]
        config = {
            "environment": args.environment,
            "region": args.region,
            "userPoolId": values.get("UserPoolId", ""),
            "userPoolClientId": values.get("UserPoolClientId", ""),
            "apiBaseUrl": "/api",
            "imagesCdnUrl": values.get("ImagesCdnUrl", ""),
            "deviceCacheTtlSeconds": app_config["images"]["browser_max_age_seconds"],
            "demoUsers": [user["email"] for user in app_config["demo_users"]],
        }
        config_path = REPO_ROOT / args.frontend_config
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        env_local = REPO_ROOT / "frontend" / ".env.local"
        env_local.write_text(f"VITE_API_PROXY={values.get('WebUrl', '')}\n", encoding="utf-8")
        print(f"--> wrote {config_path.relative_to(REPO_ROOT)} and frontend/.env.local (API proxy for npm run dev)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
