# AWS Resource Audit & Infrastructure Scan (eu-central-1)

**Scan Date:** October 14, 2026  
**AWS Account ID:** `192445490421`  
**IAM Identity:** `AWSReservedSSO_AdministratorAccess_135e82ba803ee0a0/claudiberenguer.alumno`  
**Target Region:** `eu-central-1` (Europe - Frankfurt)

---

## 1. Executive Summary

This document captures the point-in-time inventory of all AWS infrastructure deployed in region **`eu-central-1`** for the **Geo-Yield-AI** project. 

The infrastructure was replicated from `eu-south-2` (Spain) and successfully provisioned using the CloudFormation template `aws/scan_14Oct.yaml` under stack name **`geoyield-frankfurt`**.

---

## 2. Compute & Block Storage

| Resource | Identifier / Name | Type / Spec | Status | Details |
| :--- | :--- | :--- | :--- | :--- |
| **EC2 Instance** | `i-0ea3a1136e12a6166`<br>*(Geo-Yield-Server)* | `t3.micro`<br>(2 vCPU, 1 GiB RAM) | **running** | • AMI: `ami-087c4bdada7bc4dec` (Ubuntu 26.04 LTS amd64)<br>• Private IPv4: `172.31.13.102`<br>• Public IPv4: `3.64.17.221` (Elastic IP)<br>• Public DNS: `ec2-3-64-17-221.eu-central-1.compute.amazonaws.com`<br>• Subnet ID: `subnet-0674859b0ac69fdfa`<br>• Security Group: `sg-0c96200740c991757` (`geoyield-firewall`) |
| **EBS Root Volume** | `vol-095bd979582921da4` | 30 GiB (`gp3`) | **in-use** | Attached to `/dev/sda1` on `i-0ea3a1136e12a6166` (Encrypted: `True`) |
| **Elastic IP (EIP)** | `eipalloc-05546ce5feed1d854` | VPC Public IPv4 | **associated** | Public IP **`3.64.17.221`** bound to `eni-0627ca1ce909fdf10` |

---

## 3. Networking & Security

### 3.1 Virtual Private Cloud (VPC) & Subnets
- **VPC ID:** `vpc-08b4af771e0ee8d9a` (`geoyield-frankfurt-vpc`)
  - **IPv4 CIDR:** `172.31.0.0/16`
  - **DNS Support / Hostnames:** Enabled (`true`)
  - **State:** `available`
- **Internet Gateway:** Attached (`geoyield-frankfurt-igw`)
- **Public Subnet:** `subnet-0674859b0ac69fdfa` (`geoyield-frankfurt-public-subnet`)
  - **IPv4 CIDR:** `172.31.0.0/20`
  - **Availability Zone:** `eu-central-1a`
  - **Route Table:** `geoyield-frankfurt-public-rt` (`0.0.0.0/0` -> Internet Gateway)
- *(Note: Default account VPC `vpc-00fcab28a3b9a8e0c` also exists in this region but is unutilized).*

### 3.2 Security Groups

#### `geoyield-firewall` (`sg-0c96200740c991757`)
Configured firewall rules attached to `Geo-Yield-Server`:

| Port Range | Protocol | Source CIDR | Purpose |
| :--- | :--- | :--- | :--- |
| **22** | TCP | `0.0.0.0/0` | SSH remote management |
| **80** | TCP | `0.0.0.0/0` | HTTP standard ingress |
| **443** | TCP | `0.0.0.0/0` | HTTPS secure ingress |
| **8080** | TCP | `0.0.0.0/0` | FastAPI application backend / reverse proxy |
| **5432** | TCP | `185.193.174.197/32` | PostgreSQL database access (IP-restricted) |

#### Outbound (Egress)
- All traffic permitted (`-1`, `0.0.0.0/0`).

---

## 4. Object Storage (Amazon S3)

| Bucket Name | Region | Status / Encryption | Details |
| :--- | :--- | :--- | :--- |
| **`geoyield-raw-data-192445490421-eu-central-1`** | **`eu-central-1`** | ServerSideEncryption: `AES256` | • Versioning: `Enabled`<br>• Public Access Block: `All 4 Enabled`<br>• Policy: Denies non-HTTPS traffic (`aws:SecureTransport: false`)<br>• DeletionPolicy: `Retain` |

---

## 5. Managed AWS Services Status (`eu-central-1`)

- **Amazon RDS (Relational Database Service):** `0` instances (PostgreSQL runs self-hosted directly on the EC2 host).
- **AWS Lambda:** `0` serverless functions.
- **Amazon Cognito:** `0` user pools in `eu-central-1`.
- **Amazon ECR (Container Registry):** `0` container repositories.
- **Amazon CloudWatch Logs:** `0` custom log groups currently created in `eu-central-1`.

---

## 6. Infrastructure-as-Code (CloudFormation)

The infrastructure in `eu-central-1` is fully tracked and managed by AWS CloudFormation:

- **Stack Name:** `geoyield-frankfurt`
- **Stack ID:** `arn:aws:cloudformation:eu-central-1:192445490421:stack/geoyield-frankfurt/b71356e0-c7fc-11f1-bd56-06df5dbdc923`
- **Stack Status:** `CREATE_COMPLETE`

### Stack Outputs & Cross-Stack Exports

| Output Key | Export Name | Value |
| :--- | :--- | :--- |
| `ServerInstanceId` | `geoyield-frankfurt-InstanceId` | `i-0ea3a1136e12a6166` |
| `ServerPublicIp` | `geoyield-frankfurt-PublicIp` | `3.64.17.221` |
| `ServerPublicDns` | *(none)* | `ec2-3-64-17-221.eu-central-1.compute.amazonaws.com` |
| `ServerSecurityGroupId` | `geoyield-frankfurt-SecurityGroupId` | `sg-0c96200740c991757` |
| `VpcId` | `geoyield-frankfurt-VpcId` | `vpc-08b4af771e0ee8d9a` |
| `PublicSubnetId` | `geoyield-frankfurt-PublicSubnetId` | `subnet-0674859b0ac69fdfa` |
| `RawDataBucketName` | `geoyield-frankfurt-RawDataBucket` | `geoyield-raw-data-192445490421-eu-central-1` |
| `RawDataBucketArn` | *(none)* | `arn:aws:s3:::geoyield-raw-data-192445490421-eu-central-1` |

---

## 7. Comparison with `eu-south-2` Baseline

| Attribute | `eu-south-2` (Spain) | `eu-central-1` (Frankfurt) |
| :--- | :--- | :--- |
| **EC2 Instance** | `i-04d5fca0c412a861c` (`15.217.22.254`) | `i-0ea3a1136e12a6166` (`3.64.17.221`) |
| **Instance Type** | `t3.micro` | `t3.micro` |
| **Operating System** | Ubuntu 26.04 LTS amd64 | Ubuntu 26.04 LTS amd64 |
| **EBS Storage** | 30 GiB `gp3` | 30 GiB `gp3` (Encrypted) |
| **VPC** | Default VPC (`vpc-0f951ec9631152a85`) | Dedicated VPC (`vpc-08b4af771e0ee8d9a`) |
| **Firewall** | `geoyield-firewall` (`sg-0bdcf62d14ad3c02b`) | `geoyield-firewall` (`sg-0c96200740c991757`) |
| **Ports Open** | 22, 80, 443, 8080 (0.0.0.0/0), 5432 (CIDR) | 22, 80, 443, 8080 (0.0.0.0/0), 5432 (CIDR) |
| **S3 Raw Data** | `geoyield-raw-data-2026` | `geoyield-raw-data-192445490421-eu-central-1` |
| **IaC Tracking** | Manual / ClickOps | CloudFormation (`geoyield-frankfurt`) |
