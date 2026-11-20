import aws_cdk as cdk


def add_tags_to_app(
    app: cdk.App,
    main_resources_name: str,
    deployment_environment: str,
) -> None:
    """Add tags to all resources in the CDK app."""
    tags = app.node.try_get_context("tags")

    # Global tags from cdk.json
    if tags:
        for key, value in tags.items():
            cdk.Tags.of(app).add(key, value)

    # Standard tags
    cdk.Tags.of(app).add("Environment", deployment_environment)
    cdk.Tags.of(app).add("MainResourcesName", main_resources_name)
    cdk.Tags.of(app).add("ManagedBy", "CDK")
