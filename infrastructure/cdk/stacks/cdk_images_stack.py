# Built-in imports
import json

# External imports
from aws_cdk import (
    Aws,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Size,
    Stack,
    aws_cloudfront,
    aws_cloudfront_origins,
    aws_cloudwatch,
    aws_dynamodb,
    aws_lambda,
    aws_logs,
    aws_s3,
    aws_s3_deployment,
    aws_s3_notifications,
    aws_sqs,
)
from constructs import Construct

# Own imports
from helpers.paths import (
    PATH_TO_IMAGE_NEGOTIATION_FUNCTION,
    PATH_TO_IMAGE_OPTIMIZER,
    PATH_TO_ORIGINAL_IMAGES,
    PATH_TO_PILLOW_LAYER,
)
from helpers.waf import create_cloudfront_web_acl

IMAGE_SUFFIXES = [".png", ".jpg", ".jpeg", ".webp"]

# Response headers the portal reads with fetch() to explain where each image came from
EXPOSED_HEADERS = [
    "age",
    "cache-control",
    "content-length",
    "content-type",
    "date",
    "etag",
    "last-modified",
    "server-timing",
    "vary",
    "x-cache",
    "x-amz-cf-pop",
    "x-amz-cf-id",
    "x-amz-meta-rufus-campaign",
    "x-amz-meta-rufus-image-id",
    "x-amz-meta-rufus-variant",
    "x-amz-meta-rufus-format",
    "x-amz-meta-rufus-width",
    "x-amz-meta-rufus-height",
    "x-amz-meta-rufus-quality",
    "x-amz-meta-rufus-version",
    "x-amz-meta-rufus-original-bytes",
    "x-amz-meta-rufus-original-size",
]


class ImagesStack(Stack):
    """
    Class to create the Images resources: ORIGINAL and OPTIMIZED private S3 buckets, the image optimizer Lambda
    (S3 events + Pillow layer), the images catalog (DynamoDB) and the images CDN (CloudFront + CloudFront Function
    + cache/response headers policies + WAF + observability).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        main_resources_name: str,
        app_config: dict,
        **kwargs,
    ) -> None:
        """
        :param scope (Construct): Parent of this stack, usually an 'App' or a 'Stage'.
        :param construct_id (str): The construct ID of this stack.
        :param main_resources_name (str): The main unique identifier of this stack.
        :param app_config (dict): Dictionary with relevant configuration values for the stack.
        """
        super().__init__(scope, construct_id, **kwargs)

        # Input parameters
        self.construct_id = construct_id
        self.main_resources_name = main_resources_name
        self.app_config = app_config
        self.deployment_environment = self.app_config["deployment_environment"]
        self.images_config = self.app_config["images"]
        self.is_production = self.deployment_environment == "prod"
        self.removal_policy = RemovalPolicy.RETAIN if self.is_production else RemovalPolicy.DESTROY

        # Main methods for the deployment
        self.create_s3_buckets()
        self.create_catalog_table()
        self.create_lambda_layers()
        self.create_image_optimizer_lambda()
        self.configure_s3_event_notifications()
        self.upload_original_images()
        self.create_cloudfront_function()
        self.create_cloudfront_policies()
        self.create_web_acl()
        self.create_cloudfront_distribution()
        self.configure_observability()
        self.generate_cloudformation_outputs()

    def _name(self, purpose: str) -> str:
        """Resource naming convention: {main_resources_name}-{purpose}-{deployment_environment}."""
        return f"{self.main_resources_name}-{purpose}-{self.deployment_environment}"

    def create_s3_buckets(self):
        """Method to create the ORIGINAL and OPTIMIZED private buckets (Block Public Access, SSE, TLS only)."""
        common_bucket_props = {
            "block_public_access": aws_s3.BlockPublicAccess.BLOCK_ALL,
            "public_read_access": False,
            "encryption": aws_s3.BucketEncryption.S3_MANAGED,
            "enforce_ssl": True,
            "minimum_tls_version": 1.2,
            "object_ownership": aws_s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            "removal_policy": self.removal_policy,
            "auto_delete_objects": not self.is_production,
        }

        # Source of truth uploaded by marketing (versioned to recover from accidental overwrites)
        self.original_bucket = aws_s3.Bucket(
            self,
            "OriginalBucket",
            bucket_name=f"{self._name('original')}-{Aws.ACCOUNT_ID}",
            versioned=True,
            lifecycle_rules=[
                aws_s3.LifecycleRule(
                    id="cleanup",
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                    noncurrent_version_expiration=Duration.days(30),
                )
            ],
            **common_bucket_props,
        )

        # Derived data (variants): only CloudFront can read it, through Origin Access Control (OAC)
        self.optimized_bucket = aws_s3.Bucket(
            self,
            "OptimizedBucket",
            bucket_name=f"{self._name('optimized')}-{Aws.ACCOUNT_ID}",
            versioned=False,
            lifecycle_rules=[
                aws_s3.LifecycleRule(id="cleanup", abort_incomplete_multipart_upload_after=Duration.days(1))
            ],
            **common_bucket_props,
        )

    def create_catalog_table(self):
        """Method to create the images catalog (one item per image with its version, variants and LQIP)."""
        self.catalog_table = aws_dynamodb.TableV2(
            self,
            "CatalogTable",
            table_name=self._name("catalog"),
            partition_key=aws_dynamodb.Attribute(name="campaign", type=aws_dynamodb.AttributeType.STRING),
            sort_key=aws_dynamodb.Attribute(name="image_id", type=aws_dynamodb.AttributeType.STRING),
            billing=aws_dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=aws_dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            deletion_protection=self.is_production,
            removal_policy=self.removal_policy,
        )

    def create_lambda_layers(self):
        """Method to create the Pillow layer (AVIF + WebP + JPEG encoders for arm64)."""
        if not (PATH_TO_PILLOW_LAYER / "python").exists():
            raise RuntimeError("Pillow layer not installed: run 'make install-layers' first")

        self.pillow_layer = aws_lambda.LayerVersion(
            self,
            "PillowLayer",
            layer_version_name=self._name("pillow"),
            code=aws_lambda.Code.from_asset(str(PATH_TO_PILLOW_LAYER)),
            compatible_runtimes=[aws_lambda.Runtime.PYTHON_3_14],
            compatible_architectures=[aws_lambda.Architecture.ARM_64],
            description="Pillow 13 with AVIF (libavif) and WebP support, manylinux aarch64",
            removal_policy=RemovalPolicy.DESTROY,
        )

    def create_image_optimizer_lambda(self):
        """Method to create the image optimizer Lambda (triggered by S3 events of the ORIGINAL bucket)."""
        function_name = self._name("image-optimizer")
        self.cache_control_header = (
            f"public, max-age={self.images_config['browser_max_age_seconds']}, "
            f"s-maxage={self.images_config['edge_s_maxage_seconds']}, immutable"
        )

        self.optimizer_dlq = aws_sqs.Queue(
            self,
            "ImageOptimizerDLQ",
            queue_name=self._name("image-optimizer-dlq"),
            encryption=aws_sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.optimizer_log_group = aws_logs.LogGroup(
            self,
            "ImageOptimizerLogGroup",
            log_group_name=f"/aws/lambda/{function_name}",
            retention=aws_logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.optimizer_function = aws_lambda.Function(
            self,
            "ImageOptimizerFunction",
            function_name=function_name,
            description="Builds the AVIF/WebP/JPEG variants of each original image (S3 event driven)",
            runtime=aws_lambda.Runtime.PYTHON_3_14,
            architecture=aws_lambda.Architecture.ARM_64,
            handler="handler.handler",
            code=aws_lambda.Code.from_asset(
                str(PATH_TO_IMAGE_OPTIMIZER), exclude=["__pycache__", "*.pyc", "tests"]
            ),
            layers=[self.pillow_layer],
            memory_size=self.images_config["optimizer_memory_mb"],
            timeout=Duration.seconds(self.images_config["optimizer_timeout_seconds"]),
            retry_attempts=2,
            dead_letter_queue=self.optimizer_dlq,
            log_group=self.optimizer_log_group,
            environment={
                "OPTIMIZED_BUCKET": self.optimized_bucket.bucket_name,
                "CATALOG_TABLE": self.catalog_table.table_name,
                "WIDTHS": ",".join(str(width) for width in self.images_config["widths"]),
                "FORMATS": ",".join(self.images_config["formats"]),
                "QUALITY_PROFILES": json.dumps(self.images_config["quality_profiles"]),
                "CACHE_CONTROL": self.cache_control_header,
                "LOG_LEVEL": self.app_config["log_level"],
                "METRICS_NAMESPACE": f"{self.main_resources_name}/image-optimizer",
            },
        )

        # Least privilege: read originals, write/delete variants, read/write the catalog
        self.original_bucket.grant_read(self.optimizer_function)
        self.optimized_bucket.grant_read_write(self.optimizer_function)
        self.optimized_bucket.grant_delete(self.optimizer_function)
        self.catalog_table.grant_read_write_data(self.optimizer_function)

    def configure_s3_event_notifications(self):
        """Method to route ObjectCreated/ObjectRemoved events of the ORIGINAL bucket to the optimizer."""
        destination = aws_s3_notifications.LambdaDestination(self.optimizer_function)
        for suffix in IMAGE_SUFFIXES + [".json"]:
            self.original_bucket.add_event_notification(
                aws_s3.EventType.OBJECT_CREATED,
                destination,
                aws_s3.NotificationKeyFilter(prefix="campaigns/", suffix=suffix),
            )
        for suffix in IMAGE_SUFFIXES:
            self.original_bucket.add_event_notification(
                aws_s3.EventType.OBJECT_REMOVED,
                destination,
                aws_s3.NotificationKeyFilter(prefix="campaigns/", suffix=suffix),
            )

    def upload_original_images(self):
        """Method to upload the local demo images (assets/images/original) to the ORIGINAL bucket."""
        self.original_images_deployment = aws_s3_deployment.BucketDeployment(
            self,
            "OriginalImagesDeployment",
            sources=[aws_s3_deployment.Source.asset(str(PATH_TO_ORIGINAL_IMAGES))],
            destination_bucket=self.original_bucket,
            prune=True,
            retain_on_delete=False,
            memory_limit=1024,
            ephemeral_storage_size=Size.gibibytes(2),
        )
        # The notifications must exist before the files land, otherwise no event reaches the optimizer
        notifications = self.original_bucket.node.try_find_child("Notifications")
        if notifications:
            self.original_images_deployment.node.add_dependency(notifications)
        self.original_images_deployment.node.add_dependency(self.optimizer_function)

    def create_cloudfront_function(self):
        """Method to create the viewer-request CloudFront Function that normalizes width, format and quality."""
        code = (
            PATH_TO_IMAGE_NEGOTIATION_FUNCTION.read_text(encoding="utf-8")
            .replace("__WIDTHS__", json.dumps(sorted(self.images_config["widths"])))
            .replace("__DEFAULT_WIDTH__", str(self.images_config["default_width"]))
        )
        self.image_negotiation_function = aws_cloudfront.Function(
            self,
            "ImageNegotiationFunction",
            function_name=self._name("image-negotiation"),
            comment="Normalizes width/DPR, format (Accept) and quality (Save-Data) into the URI (cache key)",
            code=aws_cloudfront.FunctionCode.from_inline(code),
            runtime=aws_cloudfront.FunctionRuntime.JS_2_0,
        )

    def create_cloudfront_policies(self):
        """Method to create the cache policy and the response headers policy of the images CDN."""
        # Cache key = normalized URI only. No headers, cookies or query strings, and NO Accept-Encoding:
        # AVIF/WebP/JPEG are already compressed, so compressed-object caching would only duplicate entries.
        self.images_cache_policy = aws_cloudfront.CachePolicy(
            self,
            "ImagesCachePolicy",
            cache_policy_name=self._name("images-cache"),
            comment="Images: URI-only cache key (variant normalized by the CloudFront Function), no compression",
            min_ttl=Duration.seconds(self.images_config["edge_min_ttl_seconds"]),
            default_ttl=Duration.seconds(self.images_config["edge_default_ttl_seconds"]),
            max_ttl=Duration.seconds(self.images_config["edge_max_ttl_seconds"]),
            header_behavior=aws_cloudfront.CacheHeaderBehavior.none(),
            query_string_behavior=aws_cloudfront.CacheQueryStringBehavior.none(),
            cookie_behavior=aws_cloudfront.CacheCookieBehavior.none(),
            enable_accept_encoding_gzip=False,
            enable_accept_encoding_brotli=False,
        )

        self.images_response_headers_policy = aws_cloudfront.ResponseHeadersPolicy(
            self,
            "ImagesResponseHeadersPolicy",
            response_headers_policy_name=self._name("images-headers"),
            comment="Images: CORS for the portal, Timing-Allow-Origin, Vary: Accept, Server-Timing, hygiene",
            cors_behavior=aws_cloudfront.ResponseHeadersCorsBehavior(
                access_control_allow_credentials=False,
                access_control_allow_headers=["*"],
                access_control_allow_methods=["GET", "HEAD"],
                # Public marketing images without credentials: any origin can read them
                access_control_allow_origins=["*"],
                access_control_expose_headers=EXPOSED_HEADERS,
                access_control_max_age=Duration.seconds(600),
                origin_override=True,
            ),
            custom_headers_behavior=aws_cloudfront.ResponseCustomHeadersBehavior(
                custom_headers=[
                    # Lets the browser Resource Timing API expose transfer sizes and Server-Timing
                    aws_cloudfront.ResponseCustomHeader(header="Timing-Allow-Origin", value="*", override=True),
                    # Same URL, different format per Accept header: shared caches must keep them apart
                    aws_cloudfront.ResponseCustomHeader(header="Vary", value="Accept", override=True),
                ]
            ),
            security_headers_behavior=aws_cloudfront.ResponseSecurityHeadersBehavior(
                content_type_options=aws_cloudfront.ResponseHeadersContentTypeOptions(override=True),
                strict_transport_security=aws_cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365), include_subdomains=True, override=True
                ),
            ),
            remove_headers=["server", "x-amz-server-side-encryption"],
            server_timing_sampling_rate=self.images_config["server_timing_sampling_rate"],
        )

    def create_web_acl(self):
        """Method to create the AWS WAF web ACL of the images CDN (required by CloudFront flat-rate plans)."""
        self.images_web_acl = None
        if self.app_config.get("enable_waf", True):
            self.images_web_acl = create_cloudfront_web_acl(
                self,
                "ImagesWebAcl",
                name=self._name("images-waf"),
                rate_limit_per_5_min=self.app_config["waf_rate_limit_images_per_5_min"],
                managed_rule_groups=["AWSManagedRulesAmazonIpReputationList", "AWSManagedRulesKnownBadInputsRuleSet"],
            )

    def create_cloudfront_distribution(self):
        """Method to create the images CDN distribution (private S3 origin with OAC + Origin Shield)."""
        origin_props = {"origin_access_levels": [aws_cloudfront.AccessLevel.READ]}
        if self.images_config.get("origin_shield_enabled"):
            origin_props.update({"origin_shield_enabled": True, "origin_shield_region": Aws.REGION})
        origin = aws_cloudfront_origins.S3BucketOrigin.with_origin_access_control(
            self.optimized_bucket, **origin_props
        )

        self.images_distribution = aws_cloudfront.Distribution(
            self,
            "ImagesDistribution",
            comment=f"{self._name('images-cdn')}: Rufus Bank campaign images",
            default_behavior=aws_cloudfront.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=aws_cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cached_methods=aws_cloudfront.CachedMethods.CACHE_GET_HEAD,
                cache_policy=self.images_cache_policy,
                response_headers_policy=self.images_response_headers_policy,
                compress=False,
                function_associations=[
                    aws_cloudfront.FunctionAssociation(
                        function=self.image_negotiation_function,
                        event_type=aws_cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            http_version=aws_cloudfront.HttpVersion.HTTP2_AND_3,
            enable_ipv6=True,
            price_class=aws_cloudfront.PriceClass[self.images_config["price_class"]],
            web_acl_id=self.images_web_acl.attr_arn if self.images_web_acl else None,
            # Missing keys return 403 from S3 with OAC: cache those errors briefly to protect the origin
            error_responses=[
                aws_cloudfront.ErrorResponse(http_status=403, ttl=Duration.seconds(60)),
                aws_cloudfront.ErrorResponse(http_status=404, ttl=Duration.seconds(60)),
            ],
        )
        self.images_domain_name = self.images_distribution.distribution_domain_name

    def configure_observability(self):
        """Method to enable standard logs v2 (CloudWatch Logs), additional metrics and a dashboard."""
        distribution_arn = (
            f"arn:aws:cloudfront::{Aws.ACCOUNT_ID}:distribution/{self.images_distribution.distribution_id}"
        )

        if self.app_config.get("enable_standard_logs", True):
            log_group_name = f"/aws/vendedlogs/cloudfront/{self._name('images-cdn')}"
            self.cdn_log_group = aws_logs.LogGroup(
                self,
                "ImagesCdnLogGroup",
                log_group_name=log_group_name,
                retention=aws_logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            )
            delivery_source = aws_logs.CfnDeliverySource(
                self,
                "ImagesCdnLogsSource",
                name=self._name("images-cdn-logs-src"),
                log_type="ACCESS_LOGS",
                resource_arn=distribution_arn,
            )
            delivery_destination = aws_logs.CfnDeliveryDestination(
                self,
                "ImagesCdnLogsDestination",
                name=self._name("images-cdn-logs-dst"),
                destination_resource_arn=(
                    f"arn:aws:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:{log_group_name}"
                ),
                output_format="json",
            )
            delivery_destination.node.add_dependency(self.cdn_log_group)
            delivery = aws_logs.CfnDelivery(
                self,
                "ImagesCdnLogsDelivery",
                delivery_source_name=delivery_source.name,
                delivery_destination_arn=delivery_destination.attr_arn,
            )
            delivery.node.add_dependency(delivery_source)
            delivery.node.add_dependency(delivery_destination)

        if self.app_config.get("enable_additional_metrics", True):
            # Up to 8 extra metrics (CacheHitRate, OriginLatency, error rates by status code) at a fixed price
            aws_cloudfront.CfnMonitoringSubscription(
                self,
                "ImagesCdnMonitoringSubscription",
                distribution_id=self.images_distribution.distribution_id,
                monitoring_subscription=aws_cloudfront.CfnMonitoringSubscription.MonitoringSubscriptionProperty(
                    realtime_metrics_subscription_config=aws_cloudfront.CfnMonitoringSubscription.RealtimeMetricsSubscriptionConfigProperty(
                        realtime_metrics_subscription_status="Enabled"
                    )
                ),
            )

        def cdn_metric(name: str, statistic: str, label: str) -> aws_cloudwatch.Metric:
            return aws_cloudwatch.Metric(
                namespace="AWS/CloudFront",
                metric_name=name,
                dimensions_map={"DistributionId": self.images_distribution.distribution_id, "Region": "Global"},
                statistic=statistic,
                period=Duration.minutes(5),
                label=label,
                region="us-east-1",
            )

        optimizer_metric_namespace = f"{self.main_resources_name}/image-optimizer"
        self.dashboard = aws_cloudwatch.Dashboard(
            self,
            "ImagesDashboard",
            dashboard_name=self._name("images"),
            default_interval=Duration.hours(24),
        )
        self.dashboard.add_widgets(
            aws_cloudwatch.TextWidget(
                markdown=(
                    "# Rufus Bank images CDN\n"
                    "Bytes are the bill: watch **BytesDownloaded** and **CacheHitRate**. "
                    "Requests and bytes include cache hits (a hit is still billed data transfer)."
                ),
                width=24,
                height=2,
            ),
            aws_cloudwatch.GraphWidget(
                title="Requests",
                left=[cdn_metric("Requests", "Sum", "Requests")],
                width=8,
            ),
            aws_cloudwatch.GraphWidget(
                title="Bytes downloaded (billed data transfer)",
                left=[cdn_metric("BytesDownloaded", "Sum", "BytesDownloaded")],
                width=8,
            ),
            aws_cloudwatch.GraphWidget(
                title="Cache hit rate % (additional metric)",
                left=[cdn_metric("CacheHitRate", "Average", "CacheHitRate")],
                left_y_axis=aws_cloudwatch.YAxisProps(min=0, max=100),
                width=8,
            ),
            aws_cloudwatch.GraphWidget(
                title="Error rates %",
                left=[
                    cdn_metric("4xxErrorRate", "Average", "4xx"),
                    cdn_metric("5xxErrorRate", "Average", "5xx"),
                ],
                width=8,
            ),
            aws_cloudwatch.GraphWidget(
                title="Image optimizer Lambda",
                left=[
                    self.optimizer_function.metric_invocations(period=Duration.minutes(5)),
                    self.optimizer_function.metric_errors(period=Duration.minutes(5)),
                ],
                right=[self.optimizer_function.metric_duration(period=Duration.minutes(5), statistic="p90")],
                width=8,
            ),
            aws_cloudwatch.GraphWidget(
                title="Original vs optimized bytes (640w AVIF)",
                left=[
                    aws_cloudwatch.Metric(
                        namespace=optimizer_metric_namespace,
                        metric_name="OriginalBytes",
                        dimensions_map={"Service": "image-optimizer"},
                        statistic="Average",
                        period=Duration.minutes(5),
                    ),
                    aws_cloudwatch.Metric(
                        namespace=optimizer_metric_namespace,
                        metric_name="OptimizedBytes640Avif",
                        dimensions_map={"Service": "image-optimizer"},
                        statistic="Average",
                        period=Duration.minutes(5),
                    ),
                ],
                width=8,
            ),
        )

    def generate_cloudformation_outputs(self):
        """Method to add the relevant CloudFormation outputs."""
        CfnOutput(self, "OriginalBucketName", value=self.original_bucket.bucket_name)
        CfnOutput(self, "OptimizedBucketName", value=self.optimized_bucket.bucket_name)
        CfnOutput(self, "CatalogTableName", value=self.catalog_table.table_name)
        CfnOutput(self, "ImageOptimizerFunctionName", value=self.optimizer_function.function_name)
        CfnOutput(self, "ImagesDistributionId", value=self.images_distribution.distribution_id)
        CfnOutput(self, "ImagesCdnUrl", value=f"https://{self.images_domain_name}")
        CfnOutput(
            self,
            "ImagesDashboardUrl",
            value=(
                f"https://{Aws.REGION}.console.aws.amazon.com/cloudwatch/home?region={Aws.REGION}"
                f"#dashboards/dashboard/{self._name('images')}"
            ),
        )
