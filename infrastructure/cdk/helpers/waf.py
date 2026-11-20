"""Reusable AWS WAF web ACL (scope CLOUDFRONT) for the distributions of the project."""

# External imports
from aws_cdk import aws_wafv2
from constructs import Construct


def _visibility(metric_name: str) -> dict:
    return {
        "cloudWatchMetricsEnabled": True,
        "metricName": metric_name,
        "sampledRequestsEnabled": True,
    }


def _managed_rule(name: str, priority: int) -> dict:
    return {
        "name": name,
        "priority": priority,
        "overrideAction": {"none": {}},
        "statement": {"managedRuleGroupStatement": {"vendorName": "AWS", "name": name}},
        "visibilityConfig": _visibility(name),
    }


def create_cloudfront_web_acl(
    scope: Construct,
    construct_id: str,
    name: str,
    rate_limit_per_5_min: int,
    managed_rule_groups: list[str],
) -> aws_wafv2.CfnWebACL:
    """
    One web ACL per distribution (a flat-rate pricing plan requires a web ACL that is not shared).
    Rules: per-IP rate limit (high, because mobile carriers use CGNAT) + AWS Managed Rules.
    """
    rules = [
        {
            "name": "RateLimitPerIp",
            "priority": 0,
            "action": {"block": {}},
            "statement": {
                "rateBasedStatement": {
                    "limit": rate_limit_per_5_min,
                    "aggregateKeyType": "IP",
                    "evaluationWindowSec": 300,
                }
            },
            "visibilityConfig": _visibility("RateLimitPerIp"),
        }
    ]
    rules += [_managed_rule(group, priority) for priority, group in enumerate(managed_rule_groups, start=1)]

    return aws_wafv2.CfnWebACL(
        scope,
        construct_id,
        name=name,
        scope="CLOUDFRONT",
        default_action={"allow": {}},
        description=f"Web ACL for {name}: per IP rate limit and AWS Managed Rules",
        visibility_config=_visibility(name.replace("-", "")[:128]),
        rules=rules,
    )
