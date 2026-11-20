# External imports
from aws_cdk import (
    Aws,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudfront,
    aws_cloudfront_origins,
    aws_s3,
    aws_s3_deployment,
)
from constructs import Construct

# Own imports
from helpers.paths import PATH_TO_FRONTEND_BUILD, PATH_TO_SPA_REWRITE_FUNCTION
from helpers.waf import create_cloudfront_web_acl


class FrontendStack(Stack):
    """
    Class to create the Frontend resources: private S3 bucket for the React build, the web CloudFront distribution
    (S3 with OAC as default behavior + /api/* to the HTTP API), SPA routing function, security headers and WAF.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        main_resources_name: str,
        app_config: dict,
        user_pool_id: str,
        user_pool_client_id: str,
        http_api_domain: str,
        images_cdn_domain: str,
        **kwargs,
    ) -> None:
        """
        :param scope (Construct): Parent of this stack, usually an 'App' or a 'Stage'.
        :param construct_id (str): The construct ID of this stack.
        :param main_resources_name (str): The main unique identifier of this stack.
        :param app_config (dict): Dictionary with relevant configuration values for the stack.
        :param user_pool_id (str): Cognito User Pool ID (Backend stack).
        :param user_pool_client_id (str): Cognito SPA client ID (Backend stack).
        :param http_api_domain (str): Domain of the HTTP API (Backend stack).
        :param images_cdn_domain (str): Domain of the images CDN distribution (Images stack).
        """
        super().__init__(scope, construct_id, **kwargs)

        # Input parameters
        self.construct_id = construct_id
        self.main_resources_name = main_resources_name
        self.app_config = app_config
        self.deployment_environment = self.app_config["deployment_environment"]
        self.user_pool_id = user_pool_id
        self.user_pool_client_id = user_pool_client_id
        self.http_api_domain = http_api_domain
        self.images_cdn_domain = images_cdn_domain
        self.is_production = self.deployment_environment == "prod"
        self.removal_policy = RemovalPolicy.RETAIN if self.is_production else RemovalPolicy.DESTROY

        # Main methods for the deployment
        self.create_s3_bucket()
        self.create_cloudfront_function()
        self.create_response_headers_policy()
        self.create_web_acl()
        self.create_cloudfront_distribution()
        self.upload_objects_to_s3()
        self.generate_cloudformation_outputs()

    def _name(self, purpose: str) -> str:
        """Resource naming convention: {main_resources_name}-{purpose}-{deployment_environment}."""
        return f"{self.main_resources_name}-{purpose}-{self.deployment_environment}"

    def create_s3_bucket(self):
        """Method to create the private bucket for the React build (no S3 website hosting, OAC only)."""
        self.frontend_bucket = aws_s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"{self._name('frontend')}-{Aws.ACCOUNT_ID}",
            block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
            public_read_access=False,
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            minimum_tls_version=1.2,
            object_ownership=aws_s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            versioned=False,
            removal_policy=self.removal_policy,
            auto_delete_objects=not self.is_production,
        )

    def create_cloudfront_function(self):
        """Method to create the SPA rewrite function (app routes -> /index.html, real errors stay real)."""
        self.spa_function = aws_cloudfront.Function(
            self,
            "SpaRewriteFunction",
            function_name=self._name("spa-rewrite"),
            comment="Rewrites application routes (no file extension) to /index.html",
            code=aws_cloudfront.FunctionCode.from_file(file_path=str(PATH_TO_SPA_REWRITE_FUNCTION)),
            runtime=aws_cloudfront.FunctionRuntime.JS_2_0,
        )

    def create_response_headers_policy(self):
        """Method to create the security headers of the portal (strict CSP, HSTS, frame and referrer policies)."""
        images_origin = f"https://{self.images_cdn_domain}"
        cognito_origin = f"https://cognito-idp.{Aws.REGION}.amazonaws.com"
        content_security_policy = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                "font-src 'self' data:",
                f"img-src 'self' data: blob: {images_origin}",
                f"connect-src 'self' {cognito_origin} {images_origin}",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
                "object-src 'none'",
                "upgrade-insecure-requests",
            ]
        )
        self.web_response_headers_policy = aws_cloudfront.ResponseHeadersPolicy(
            self,
            "WebResponseHeadersPolicy",
            response_headers_policy_name=self._name("web-headers"),
            comment="Portal: CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy",
            security_headers_behavior=aws_cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=aws_cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=content_security_policy, override=True
                ),
                strict_transport_security=aws_cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365), include_subdomains=True, override=True
                ),
                frame_options=aws_cloudfront.ResponseHeadersFrameOptions(
                    frame_option=aws_cloudfront.HeadersFrameOption.DENY, override=True
                ),
                content_type_options=aws_cloudfront.ResponseHeadersContentTypeOptions(override=True),
                referrer_policy=aws_cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=aws_cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                    override=True,
                ),
            ),
            custom_headers_behavior=aws_cloudfront.ResponseCustomHeadersBehavior(
                custom_headers=[
                    aws_cloudfront.ResponseCustomHeader(
                        header="Permissions-Policy",
                        value="camera=(), microphone=(), geolocation=(), payment=()",
                        override=True,
                    )
                ]
            ),
            remove_headers=["server", "x-amz-server-side-encryption"],
        )

    def create_web_acl(self):
        """Method to create the AWS WAF web ACL of the portal (rate limit + common, bad inputs, IP reputation)."""
        self.web_acl = None
        if self.app_config.get("enable_waf", True):
            self.web_acl = create_cloudfront_web_acl(
                self,
                "WebAcl",
                name=self._name("web-waf"),
                rate_limit_per_5_min=self.app_config["waf_rate_limit_web_per_5_min"],
                managed_rule_groups=[
                    "AWSManagedRulesAmazonIpReputationList",
                    "AWSManagedRulesCommonRuleSet",
                    "AWSManagedRulesKnownBadInputsRuleSet",
                ],
            )

    def create_cloudfront_distribution(self):
        """Method to create the web distribution: S3 (OAC) by default and /api/* to API Gateway, same origin."""
        api_origin = aws_cloudfront_origins.HttpOrigin(
            self.http_api_domain,
            protocol_policy=aws_cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            origin_ssl_protocols=[aws_cloudfront.OriginSslPolicy.TLS_V1_2],
        )

        self.web_distribution = aws_cloudfront.Distribution(
            self,
            "WebDistribution",
            comment=f"{self._name('web')}: Rufus Bank portal",
            default_root_object="index.html",
            default_behavior=aws_cloudfront.BehaviorOptions(
                origin=aws_cloudfront_origins.S3BucketOrigin.with_origin_access_control(
                    self.frontend_bucket, origin_access_levels=[aws_cloudfront.AccessLevel.READ]
                ),
                viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=aws_cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cache_policy=aws_cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=self.web_response_headers_policy,
                compress=True,
                function_associations=[
                    aws_cloudfront.FunctionAssociation(
                        function=self.spa_function,
                        event_type=aws_cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            additional_behaviors={
                # Same origin for the API: no CORS preflights, one domain, one WAF, never cached
                "/api/*": aws_cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=aws_cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                    cache_policy=aws_cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=aws_cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=self.web_response_headers_policy,
                    compress=True,
                )
            },
            http_version=aws_cloudfront.HttpVersion.HTTP2_AND_3,
            enable_ipv6=True,
            price_class=aws_cloudfront.PriceClass[self.app_config["images"]["price_class"]],
            web_acl_id=self.web_acl.attr_arn if self.web_acl else None,
        )

    def upload_objects_to_s3(self):
        """
        Method to upload the React build with the right caching per file type:
        - hashed assets (/assets/*): Cache-Control public, max-age=1 year, immutable
        - index.html and config.json: no-cache (always revalidated, so new deployments are picked up)
        """
        index_html = PATH_TO_FRONTEND_BUILD / "index.html"
        if not index_html.exists():
            raise RuntimeError("Frontend build not found: run 'make build-frontend' (frontend/dist) first")

        assets_deployment = aws_s3_deployment.BucketDeployment(
            self,
            "FrontendAssetsDeployment",
            sources=[aws_s3_deployment.Source.asset(str(PATH_TO_FRONTEND_BUILD), exclude=["index.html"])],
            destination_bucket=self.frontend_bucket,
            prune=False,
            cache_control=[aws_s3_deployment.CacheControl.from_string("public, max-age=31536000, immutable")],
            memory_limit=512,
        )

        images_config = self.app_config["images"]
        runtime_config = {
            "environment": self.deployment_environment,
            "region": Aws.REGION,
            "userPoolId": self.user_pool_id,
            "userPoolClientId": self.user_pool_client_id,
            "apiBaseUrl": "/api",
            "imagesCdnUrl": f"https://{self.images_cdn_domain}",
            "deviceCacheTtlSeconds": images_config["browser_max_age_seconds"],
            "demoUsers": [user["email"] for user in self.app_config["demo_users"]],
        }
        shell_deployment = aws_s3_deployment.BucketDeployment(
            self,
            "FrontendShellDeployment",
            sources=[
                aws_s3_deployment.Source.data("index.html", index_html.read_text(encoding="utf-8")),
                aws_s3_deployment.Source.json_data("config.json", runtime_config),
            ],
            destination_bucket=self.frontend_bucket,
            prune=False,
            cache_control=[aws_s3_deployment.CacheControl.from_string("no-cache")],
            distribution=self.web_distribution,
            distribution_paths=["/", "/index.html", "/config.json"],
            memory_limit=512,
        )
        # The new index.html must only appear after the hashed assets it references are uploaded
        shell_deployment.node.add_dependency(assets_deployment)

    def generate_cloudformation_outputs(self):
        """Method to add the relevant CloudFormation outputs."""
        CfnOutput(self, "FrontendBucketName", value=self.frontend_bucket.bucket_name)
        CfnOutput(self, "WebDistributionId", value=self.web_distribution.distribution_id)
        CfnOutput(self, "WebUrl", value=f"https://{self.web_distribution.distribution_domain_name}")
