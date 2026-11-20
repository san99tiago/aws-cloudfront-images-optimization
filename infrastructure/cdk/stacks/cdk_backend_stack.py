# Built-in imports
import json

# External imports
from aws_cdk import (
    Aws,
    CfnOutput,
    CfnParameter,
    CustomResource,
    Duration,
    RemovalPolicy,
    SecretValue,
    Stack,
    aws_apigatewayv2,
    aws_apigatewayv2_authorizers,
    aws_apigatewayv2_integrations,
    aws_cognito,
    aws_dynamodb,
    aws_lambda,
    aws_logs,
    aws_secretsmanager,
    custom_resources,
)
from constructs import Construct

# Own imports
from helpers.paths import PATH_TO_PROFILE_API, PATH_TO_USERS_SEEDER


class BackendStack(Stack):
    """
    Class to create the Backend resources: Cognito User Pool (no self sign-up, 3 seeded demo users), the users
    profile table (DynamoDB, PK user_email), the profile Lambda and the HTTP API (API Gateway + JWT authorizer).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        main_resources_name: str,
        app_config: dict,
        catalog_table: aws_dynamodb.ITableV2,
        images_cdn_url: str,
        **kwargs,
    ) -> None:
        """
        :param scope (Construct): Parent of this stack, usually an 'App' or a 'Stage'.
        :param construct_id (str): The construct ID of this stack.
        :param main_resources_name (str): The main unique identifier of this stack.
        :param app_config (dict): Dictionary with relevant configuration values for the stack.
        :param catalog_table (ITableV2): Images catalog table (from the Images stack).
        :param images_cdn_url (str): Base URL of the images CDN (from the Images stack).
        """
        super().__init__(scope, construct_id, **kwargs)

        # Input parameters
        self.construct_id = construct_id
        self.main_resources_name = main_resources_name
        self.app_config = app_config
        self.deployment_environment = self.app_config["deployment_environment"]
        self.catalog_table = catalog_table
        self.images_cdn_url = images_cdn_url
        self.is_production = self.deployment_environment == "prod"
        self.removal_policy = RemovalPolicy.RETAIN if self.is_production else RemovalPolicy.DESTROY

        # Main methods for the deployment
        self.create_demo_users_secret()
        self.create_users_table()
        self.create_cognito_user_pool()
        self.create_users_seeder()
        self.create_profile_lambda()
        self.create_http_api()
        self.generate_cloudformation_outputs()

    def _name(self, purpose: str) -> str:
        """Resource naming convention: {main_resources_name}-{purpose}-{deployment_environment}."""
        return f"{self.main_resources_name}-{purpose}-{self.deployment_environment}"

    def create_demo_users_secret(self):
        """
        Method to store the demo users password in Secrets Manager.
        The value arrives as a NoEcho CloudFormation parameter (from .env through the Makefile), so it never
        lands in the synthesized template, the CDK assets or the custom resource properties.
        """
        password_parameter = CfnParameter(
            self,
            "DemoUsersPassword",
            type="String",
            no_echo=True,
            min_length=8,
            description="Password of the demo Cognito users (NoEcho, read from .env by 'make deploy')",
        )
        self.demo_users_secret = aws_secretsmanager.Secret(
            self,
            "DemoUsersSecret",
            secret_name=self._name("demo-users"),
            description="Shared password of the Rufus Bank demo users (read at runtime by the seeder Lambda)",
            secret_string_value=SecretValue.cfn_parameter(password_parameter),
            removal_policy=RemovalPolicy.DESTROY,
        )

    def create_users_table(self):
        """Method to create the users profile table: business metadata that is NOT inside the JWT."""
        self.users_table = aws_dynamodb.TableV2(
            self,
            "UsersTable",
            table_name=self._name("users"),
            partition_key=aws_dynamodb.Attribute(name="user_email", type=aws_dynamodb.AttributeType.STRING),
            billing=aws_dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=aws_dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            deletion_protection=self.is_production,
            removal_policy=self.removal_policy,
        )

    def create_cognito_user_pool(self):
        """Method to create the Cognito User Pool (admin-created users only) and the public SPA client."""
        self.user_pool = aws_cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=self._name("users"),
            self_sign_up_enabled=False,
            sign_in_aliases=aws_cognito.SignInAliases(email=True, username=False),
            sign_in_case_sensitive=False,
            auto_verify=aws_cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=aws_cognito.StandardAttributes(
                email=aws_cognito.StandardAttribute(required=True, mutable=True)
            ),
            password_policy=aws_cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(1),
            ),
            account_recovery=aws_cognito.AccountRecovery.NONE,
            mfa=aws_cognito.Mfa.OFF,
            feature_plan=aws_cognito.FeaturePlan.ESSENTIALS,
            deletion_protection=self.is_production,
            removal_policy=self.removal_policy,
        )

        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=self._name("web"),
            generate_secret=False,
            # SRP for the SPA (the password never travels); admin auth only for the IAM-authenticated E2E tests
            auth_flows=aws_cognito.AuthFlow(user_srp=True, admin_user_password=True),
            disable_o_auth=True,
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=Duration.minutes(60),
            id_token_validity=Duration.minutes(60),
            refresh_token_validity=Duration.days(1),
            read_attributes=aws_cognito.ClientAttributes().with_standard_attributes(email=True, email_verified=True),
            write_attributes=aws_cognito.ClientAttributes().with_standard_attributes(email=True),
        )

    def create_users_seeder(self):
        """Method to create the 3 demo users (permanent password) and map them in DynamoDB (custom resource)."""
        function_name = self._name("users-seeder")
        self.seeder_function = aws_lambda.Function(
            self,
            "UsersSeederFunction",
            function_name=function_name,
            description="Custom resource: creates the demo Cognito users and their DynamoDB profiles",
            runtime=aws_lambda.Runtime.PYTHON_3_14,
            architecture=aws_lambda.Architecture.ARM_64,
            handler="handler.handler",
            code=aws_lambda.Code.from_asset(str(PATH_TO_USERS_SEEDER), exclude=["__pycache__", "*.pyc"]),
            timeout=Duration.seconds(60),
            memory_size=256,
            log_group=aws_logs.LogGroup(
                self,
                "UsersSeederLogGroup",
                log_group_name=f"/aws/lambda/{function_name}",
                retention=aws_logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            ),
            environment={
                "USER_POOL_ID": self.user_pool.user_pool_id,
                "USERS_TABLE": self.users_table.table_name,
                "DEMO_USERS_SECRET_ARN": self.demo_users_secret.secret_arn,
                "LOG_LEVEL": self.app_config["log_level"],
            },
        )
        self.user_pool.grant(
            self.seeder_function,
            "cognito-idp:AdminCreateUser",
            "cognito-idp:AdminSetUserPassword",
            "cognito-idp:AdminGetUser",
            "cognito-idp:AdminDeleteUser",
        )
        self.users_table.grant_read_write_data(self.seeder_function)
        self.demo_users_secret.grant_read(self.seeder_function)

        provider = custom_resources.Provider(
            self,
            "UsersSeederProvider",
            on_event_handler=self.seeder_function,
            log_group=aws_logs.LogGroup(
                self,
                "UsersSeederProviderLogGroup",
                retention=aws_logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        self.demo_users = CustomResource(
            self,
            "DemoUsers",
            service_token=provider.service_token,
            resource_type="Custom::RufusDemoUsers",
            properties={
                # Only public profile data travels here (never the password)
                "Users": json.dumps(self.app_config["demo_users"], ensure_ascii=False),
                "SeedVersion": str(self.app_config.get("demo_users_seed_version", "1")),
            },
        )
        self.demo_users.node.add_dependency(self.demo_users_secret)

    def create_profile_lambda(self):
        """Method to create the profile Lambda (JWT claims + DynamoDB profile + segmented catalog)."""
        images_config = self.app_config["images"]
        function_name = self._name("profile-api")
        self.profile_function = aws_lambda.Function(
            self,
            "ProfileApiFunction",
            function_name=function_name,
            description="GET /api/me: profile from DynamoDB and the campaigns allowed by the risk profile",
            runtime=aws_lambda.Runtime.PYTHON_3_14,
            architecture=aws_lambda.Architecture.ARM_64,
            handler="handler.handler",
            code=aws_lambda.Code.from_asset(str(PATH_TO_PROFILE_API), exclude=["__pycache__", "*.pyc"]),
            timeout=Duration.seconds(10),
            memory_size=512,
            log_group=aws_logs.LogGroup(
                self,
                "ProfileApiLogGroup",
                log_group_name=f"/aws/lambda/{function_name}",
                retention=aws_logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            ),
            environment={
                "USERS_TABLE": self.users_table.table_name,
                "CATALOG_TABLE": self.catalog_table.table_name,
                "CAMPAIGNS": json.dumps(self.app_config["campaigns"], ensure_ascii=False),
                "IMAGES_CDN_URL": self.images_cdn_url,
                "IMAGES_CONFIG": json.dumps(
                    {
                        "widths": sorted(images_config["widths"]),
                        "default_width": images_config["default_width"],
                        "formats": images_config["formats"],
                        "quality_tiers": list(images_config["quality_profiles"].keys()),
                        "quality_profiles": images_config["quality_profiles"],
                        "browser_max_age_seconds": images_config["browser_max_age_seconds"],
                        "edge_s_maxage_seconds": images_config["edge_s_maxage_seconds"],
                        "edge_min_ttl_seconds": images_config["edge_min_ttl_seconds"],
                        "edge_default_ttl_seconds": images_config["edge_default_ttl_seconds"],
                        "edge_max_ttl_seconds": images_config["edge_max_ttl_seconds"],
                        "price_class": images_config["price_class"],
                        "origin_shield_enabled": images_config["origin_shield_enabled"],
                    }
                ),
                "LOG_LEVEL": self.app_config["log_level"],
            },
        )
        self.users_table.grant_read_data(self.profile_function)
        self.catalog_table.grant_read_data(self.profile_function)

    def create_http_api(self):
        """Method to create the HTTP API (API Gateway) with the Cognito JWT authorizer, throttling and access logs."""
        self.http_api = aws_apigatewayv2.HttpApi(
            self,
            "HttpApi",
            api_name=self._name("api"),
            description="Rufus Bank portal API (always behind the web CloudFront distribution at /api/*)",
            create_default_stage=True,
        )
        authorizer = aws_apigatewayv2_authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer",
            self.user_pool,
            user_pool_clients=[self.user_pool_client],
            identity_source=["$request.header.Authorization"],
        )
        self.http_api.add_routes(
            path="/api/me",
            methods=[aws_apigatewayv2.HttpMethod.GET],
            integration=aws_apigatewayv2_integrations.HttpLambdaIntegration(
                "ProfileIntegration", handler=self.profile_function
            ),
            authorizer=authorizer,
        )

        access_logs = aws_logs.LogGroup(
            self,
            "HttpApiAccessLogs",
            log_group_name=f"/aws/apigateway/{self._name('api')}",
            retention=aws_logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        stage = self.http_api.default_stage.node.default_child
        stage.access_log_settings = aws_apigatewayv2.CfnStage.AccessLogSettingsProperty(
            destination_arn=access_logs.log_group_arn,
            format=json.dumps(
                {
                    "requestId": "$context.requestId",
                    "ip": "$context.identity.sourceIp",
                    "requestTime": "$context.requestTime",
                    "httpMethod": "$context.httpMethod",
                    "routeKey": "$context.routeKey",
                    "status": "$context.status",
                    "responseLength": "$context.responseLength",
                    "integrationLatency": "$context.integrationLatency",
                    "authorizerError": "$context.authorizer.error",
                }
            ),
        )
        stage.default_route_settings = aws_apigatewayv2.CfnStage.RouteSettingsProperty(
            throttling_rate_limit=self.app_config["api_throttling_rate_limit"],
            throttling_burst_limit=self.app_config["api_throttling_burst_limit"],
        )
        self.http_api_domain = f"{self.http_api.api_id}.execute-api.{Aws.REGION}.amazonaws.com"

    def generate_cloudformation_outputs(self):
        """Method to add the relevant CloudFormation outputs."""
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
        CfnOutput(self, "UsersTableName", value=self.users_table.table_name)
        CfnOutput(self, "HttpApiUrl", value=self.http_api.api_endpoint)
        CfnOutput(self, "DemoUsersSecretName", value=self._name("demo-users"))
        CfnOutput(self, "ProfileFunctionName", value=self.profile_function.function_name)
