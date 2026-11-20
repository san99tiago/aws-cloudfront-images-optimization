"""
Rufus Bank demo users seeder (CloudFormation custom resource through the CDK Provider framework).

Create / Update:
- Creates each Cognito user (email as username, email_verified=true, invitation e-mail SUPPRESSED)
- Sets the shared password as PERMANENT (no forced change at first login)
- Maps the user in DynamoDB (PK user_email) with its business metadata (name, role, score, risk_profile)
- Removes users that were dropped from the list (on Update)

Delete: removes the demo users and their DynamoDB items.

The password is NEVER part of the custom resource properties: it is read at runtime from AWS Secrets Manager.
"""

# Built-in imports
import json
import logging
import os
from datetime import datetime, timezone

# External imports
import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

COGNITO = boto3.client("cognito-idp")
SECRETS = boto3.client("secretsmanager")
TABLE = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"])
USER_POOL_ID = os.environ["USER_POOL_ID"]
SECRET_ARN = os.environ["DEMO_USERS_SECRET_ARN"]


def _password() -> str:
    return SECRETS.get_secret_value(SecretId=SECRET_ARN)["SecretString"]


def _upsert_user(user: dict, password: str) -> str:
    email = user["email"].lower()
    try:
        COGNITO.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )
        LOGGER.info(json.dumps({"message": "user created", "email": email}))
    except COGNITO.exceptions.UsernameExistsException:
        LOGGER.info(json.dumps({"message": "user already exists", "email": email}))

    # Permanent password: the user is CONFIRMED and never sees NEW_PASSWORD_REQUIRED
    COGNITO.admin_set_user_password(UserPoolId=USER_POOL_ID, Username=email, Password=password, Permanent=True)
    attributes = COGNITO.admin_get_user(UserPoolId=USER_POOL_ID, Username=email)["UserAttributes"]
    sub = next((attribute["Value"] for attribute in attributes if attribute["Name"] == "sub"), None)

    TABLE.put_item(
        Item={
            "user_email": email,
            "name": user["name"],
            "role": user["role"],
            "score": int(user["score"]),
            "risk_profile": user["risk_profile"].upper(),
            "cognito_sub": sub,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return email


def _delete_user(email: str) -> None:
    try:
        COGNITO.admin_delete_user(UserPoolId=USER_POOL_ID, Username=email)
    except COGNITO.exceptions.UserNotFoundException:
        pass
    TABLE.delete_item(Key={"user_email": email})
    LOGGER.info(json.dumps({"message": "user deleted", "email": email}))


def handler(event, context):
    request_type = event["RequestType"]
    users = json.loads(event["ResourceProperties"]["Users"])
    physical_id = event.get("PhysicalResourceId") or f"{USER_POOL_ID}-demo-users"

    if request_type in ("Create", "Update"):
        password = _password()
        seeded = [_upsert_user(user, password) for user in users]
        if request_type == "Update":
            previous = json.loads(event.get("OldResourceProperties", {}).get("Users", "[]"))
            current = {user["email"].lower() for user in users}
            for old_user in previous:
                if old_user["email"].lower() not in current:
                    _delete_user(old_user["email"].lower())
        return {"PhysicalResourceId": physical_id, "Data": {"SeededUsers": ",".join(seeded)}}

    if request_type == "Delete":
        for user in users:
            try:
                _delete_user(user["email"].lower())
            except Exception as error:  # noqa: BLE001 (never block a stack deletion)
                LOGGER.warning(json.dumps({"message": "delete failed", "error": str(error)}))
        return {"PhysicalResourceId": physical_id}

    return {"PhysicalResourceId": physical_id}
