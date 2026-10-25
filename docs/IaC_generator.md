# Exporting the AWS infrastructure to CloudFormation (IaC Generator)

**Status:** Operational guide. **Date:** October 2026.

The frontend bucket, CloudFront distribution, EC2 instance, security groups and (later) RDS were created by hand in the console. The **CloudFormation IaC generator** scans existing resources and produces a template, so the infrastructure can be versioned and recreated. Save the result under `aws/cloudformation/` (not created yet).

## What to scan, and where

| Resource | Type | Region to scan from |
| --- | --- | --- |
| CloudFront distribution and Origin Access Control | `AWS::CloudFront::Distribution`, `AWS::CloudFront::OriginAccessControl` | **`us-east-1`** (global control plane) |
| Frontend bucket and policy | `AWS::S3::Bucket`, `AWS::S3::BucketPolicy` | `eu-central-1` |
| API host with its network interfaces, security groups and instance profile | `AWS::EC2::Instance` | `eu-central-1` |
| Database (once on RDS) | `AWS::RDS::DBInstance` | `eu-central-1` |

## Procedure

1. In the console, open **CloudFormation → IaC generator** in the right region.
2. **Start a scan.** Use a full scan for a first baseline, or a partial scan limited to the types above. It takes 2-10 minutes and results are kept 30 days (you can derive several templates from one scan).
3. **Create template** from the finished scan. Choose *Start from a new template*, set a name such as `geoyield-frontend`, and set both *Deletion policy* and *Update replace policy* to **Retain**, so a stack change can never delete a live database, bucket or distribution.
4. **Select resources**, filtering by type, ID or tag (for example the frontend bucket and distribution), then accept the suggested **related resources** (cache and origin request policies, OAC, bucket policy, DNS records) to avoid broken references.
5. **Review and create.** If a resource has write-only properties (passwords, KMS keys), click *Resolve* and replace them with parameters or `{{resolve:secretsmanager:...}}` references.
6. **Download** the template as YAML or JSON.

CloudFront only: `aws cloudfront get-distribution-config --id <ID> | jq '.DistributionConfig' > distribution-config.json` exports its configuration without a scan.

## Hardening checklist before deploying a generated template

- [ ] Replace hard-coded physical names with parameters or `!Sub "${AWS::StackName}-..."`.
- [ ] Viewer certificate `MinimumProtocolVersion` is `TLSv1.2_2021` or newer.
- [ ] The distribution uses an Origin Access Control, not a legacy Origin Access Identity.
- [ ] Custom error responses map `403` and `404` to `/index.html` with status `200` (history-mode routing).
- [ ] No secrets, account IDs or key material remain in the template.
