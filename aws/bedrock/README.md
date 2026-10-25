# Amazon Bedrock & CloudWatch IAM Configuration for EC2

This directory contains the IAM policies and instructions to allow the backend on Amazon EC2 (`Geo-Yield-Server` in `eu-central-1`) to invoke Amazon Bedrock foundation models and push observability logs without static credentials.

## Files

- `trust-policy.json`: Allows `ec2.amazonaws.com` to assume the IAM role.
- `bedrock-policy.json`: Permissions for Bedrock model inference, streaming, reranking, and CloudWatch logs.

## Provisioned Resources

- **Role Name:** `GeoYield-EC2-Bedrock-Role`
- **Instance Profile Name:** `GeoYield-EC2-Bedrock-Instance-Profile`
- **Target Instance:** `i-0ea3a1136e12a6166` (`Geo-Yield-Server`, `eu-central-1`)
