# Assessment: Scanning AWS Infrastructure to CloudFormation via IaC Generator

**Document Status:** Operational Guide & Technical Assessment  
**Date:** October 2026  
**Target Systems:** Amazon CloudFront, Amazon S3, Amazon EC2, Amazon RDS PostgreSQL, IAM, Route 53  
**Target Regions:** `eu-central-1` (Frankfurt) / `eu-south-2` (Spain) / `us-east-1` (CloudFront Global Catalog)  
**IaC Target Formats:** AWS CloudFormation (YAML / JSON) & AWS CDK (TypeScript / Python)

---

## 1. Executive Summary & Purpose

The **AWS CloudFormation IaC (Infrastructure as Code) Generator** allows cloud teams to scan existing AWS resources provisioned manually (via the AWS Management Console / "ClickOps" or scripts) and automatically generate production-ready CloudFormation templates or migrate them directly into an AWS CDK application.

In the **Geo-Yield-AI** project, several core infrastructure components—including the frontend S3 bucket, CloudFront distribution with Origin Access Control (OAC), EC2 Graviton API instance, security groups, and RDS PostgreSQL database—were created or assessed manually across `eu-central-1` and `eu-south-2`. 

This assessment provides the technical blueprint and console procedure for scanning these deployed resources, mapping their dependencies, and exporting them to a version-controlled CloudFormation template file.

---

## 2. Infrastructure Inventory & Regional Considerations

Before initiating a scan in the AWS Console, it is essential to understand how AWS classifies regional and global resources:

| Resource Type | Service Identifier | Scope / Region | Notes |
| :--- | :--- | :--- | :--- |
| **CloudFront Distribution** | `AWS::CloudFront::Distribution` | **Global (`us-east-1`)** | Managed via global control plane; CloudFront and Route 53 resources must be scanned from the `us-east-1` (N. Virginia) console. |
| **CloudFront Origin Access Control** | `AWS::CloudFront::OriginAccessControl` | **Global (`us-east-1`)** | Associated with S3 origin security. |
| **Frontend Storage Bucket** | `AWS::S3::Bucket` | Regional (`eu-central-1` / `eu-south-2`) | S3 buckets exist globally by name but reside in specific target regions. |
| **S3 Bucket Policy** | `AWS::S3::BucketPolicy` | Regional | Grants read access to CloudFront OAC. |
| **Backend Compute** | `AWS::EC2::Instance` | Regional (`eu-central-1`) | Includes attached ENIs, Security Groups, and IAM Instance Profiles. |
| **Relational Database** | `AWS::RDS::DBInstance` | Regional (`eu-central-1`) | PostgreSQL PostGIS + pgvector database and subnet groups. |

---

## 3. Step-by-Step Console Guide: Using CloudFormation IaC Generator

### Step 1: Open the IaC Generator in the AWS Console
1. Log in to the **AWS Management Console**.
2. Set your console region in the top navigation bar:
   * To scan regional resources (EC2, RDS, S3), choose **`eu-central-1` (Frankfurt)**.
   * To scan the **CloudFront distribution** and OAC, choose **`us-east-1` (N. Virginia)**.
3. In the unified search bar, search for **CloudFormation** and open the service.
4. In the left-hand navigation pane, select **IaC generator**.

---

### Step 2: Initiate a Resource Scan
1. On the **IaC generator** dashboard, navigate to the **Scans** card.
2. Click **Start a new scan** (or **Scan resources**).
3. Select the scan scope:
   * **Full scan:** Scans all supported AWS resources in your current region and account (recommended for initial baseline).
   * **Partial scan:** Allows you to target specific resource types:
     * `AWS::CloudFront::Distribution`
     * `AWS::CloudFront::OriginAccessControl`
     * `AWS::S3::Bucket`
     * `AWS::EC2::Instance`
     * `AWS::RDS::DBInstance`
4. Click **Start scan**.
   * *Duration:* Scans usually complete in 2 to 10 minutes depending on resource count.
   * *Retention:* Scan results are preserved in your account for **30 days**. You can create multiple templates from a single scan.

---

### Step 3: Create a CloudFormation Template from Scanned Resources
1. Once the scan status displays **Complete**, scroll down to the **Templates** section.
2. Click **Create template**.
3. Under **Prerequisite - Prepare template**, select **Start from a new template**.
4. Configure template details:
   * **Template name:** e.g., `geoyield-frontend-cloudfront-template`
   * **Deletion policy:** Select **Retain**  
     *(Crucial security practice: prevents CloudFormation from deleting live databases, S3 buckets, or distributions during stack updates or deletions).*
   * **Update replace policy:** Select **Retain**.
   * Click **Next**.

---

### Step 4: Select Scanned Resources & Map Dependencies
1. **Add scanned resources:**
   * Use the search bar and filters (by resource type, identifier, or tags) to select your target infrastructure (e.g., your CloudFront distribution ID `d2yya2azx26rn0...` or S3 bucket `geoyield-frontend`).
   * Click **Next**.
2. **Add related resources:**
   * The IaC generator evaluates the Cloud Control API graph and automatically identifies associated resources (e.g., Origin Request Policies, Cache Policies, OAC configurations, S3 Bucket Policies, Route 53 Record Sets).
   * Review and select all suggested related resources to prevent broken references in the resulting template.
   * Click **Next**.

---

### Step 5: Review, Resolve Properties, and Export
1. On the **Review and create** screen, review all selected resources and relationships.
2. Click **Create template**.
3. If any resource contains **Write-only properties** (such as sensitive passwords or KMS keys that cannot be retrieved by Cloud Control API), CloudFormation will flag them with a warning:
   * Click **Resolve** and substitute dynamic references (e.g., `{{resolve:secretsmanager:...}}` or parameters).
4. When template generation reaches **Complete**, open the template details page.
5. In the top-right corner, click **Download**:
   * Choose **YAML** (standard human-readable CloudFormation) or **JSON**.
   * Save the generated file locally into your repository (e.g., `aws/cloudformation/template.yaml`).

---

## 4. Alternative: Exporting CloudFront Distribution Configuration Directly

If the objective is exclusively to extract the CloudFront configuration without running a full CloudFormation resource scan:

### 4.1 Via AWS CLI
Run the following command to retrieve the exact JSON configuration of the CloudFront distribution:

```bash
# Retrieve distribution configuration and save to a JSON file
aws cloudfront get-distribution-config \
  --id <DISTRIBUTION_ID> \
  --output json > cloudfront-config.json
```

To extract only the core `DistributionConfig` block ready for updates or IaC translation:
```bash
jq '.DistributionConfig' cloudfront-config.json > distribution-config-clean.json
```

### 4.2 Via CloudFront Management Console
1. Navigate to **CloudFront** in the AWS Console.
2. Click on the target distribution.
3. Navigate through the **General**, **Origins**, and **Behaviors** tabs to review or copy origin paths, OAC IDs, and custom error response mappings.
*(Note: The CloudFront console does not provide a single-click "Download Configuration File" button; the AWS CLI or CloudFormation IaC generator are the recommended programmatic approaches).*

---

## 5. Post-Generation Template Hardening Checklist

When incorporating the generated template into the `PJ` repository, apply the following standards before running stack deployments:

- [ ] **Remove Physical Resource Names:** Replace hardcoded names with parameter-derived or stack-prefixed names (`!Sub "${AWS::StackName}-frontend-bucket"`).
- [ ] **Enforce TLS 1.3 on CloudFront:** Verify `ViewerCertificate` uses `MinimumProtocolVersion: TLSv1.2_2021` or `TLSv1.3`.
- [ ] **S3 Origin Access Control (OAC):** Ensure the distribution references an `AWS::CloudFront::OriginAccessControl` rather than legacy Origin Access Identity (OAI).
- [ ] **SPA Fallback Routing:** Confirm custom error responses map `403` and `404` HTTP status codes to `/index.html` with HTTP `200` response for Vue Router history mode.
- [ ] **Add Tooling Metadata:** Include the project's tracking metadata at the top of the template:
  ```yaml
  Metadata:
    AWSToolsMetrics:
      AWSAgentToolkit: aws-cloudformation@3
      IaC_Generator: v1.0
  ```
