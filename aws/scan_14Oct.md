# AWS Resource Audit & Infrastructure Scan (eu-south-2)

**Scan Date:** October 14, 2026  
**AWS Account ID:** `192445490421`  
**IAM Identity:** `AWSReservedSSO_AdministratorAccess_135e82ba803ee0a0/claudiberenguer.alumno`  
**Target Region:** `eu-south-2` (Europe - Spain)

---

## 1. Executive Summary

This document captures the point-in-time inventory of all AWS infrastructure deployed in region `eu-south-2` for the **Geo-Yield-AI** project. 

The architecture in `eu-south-2` currently operates a single-node host running backend services and database workloads, connected to global edge delivery via Amazon CloudFront.

---

## 2. Compute & Block Storage

| Resource | Identifier / Name | Type / Spec | Status | Details |
| :--- | :--- | :--- | :--- | :--- |
| **EC2 Instance** | `i-04d5fca0c412a861c`<br>*(Geo-Yield-Server)* | `t3.micro`<br>(2 vCPU, 1 GiB RAM) | **running** | • Private IPv4: `172.31.25.118`<br>• Public IPv4: `15.217.22.254` (Elastic IP)<br>• Public DNS: `ec2-15-217-22-254.eu-south-2.compute.amazonaws.com`<br>• IAM Instance Profile: None (unassigned) |
| **EBS Root Volume** | `vol-0fa06402e6499bba1` | 30 GiB (`gp3`) | **in-use** | Attached to `/dev/xvda` on `i-04d5fca0c412a861c` |
| **Elastic IP (EIP)** | `eipalloc-05e131623fd03daff` | VPC Public IPv4 | **associated** | Public IP `15.217.22.254` bound to `eni-0e5138a6d4a104f66` |

---

## 3. Networking & Security

### 3.1 Virtual Private Cloud (VPC)
- **VPC ID:** `vpc-0f951ec9631152a85` (Default VPC)
- **IPv4 CIDR:** `172.31.0.0/16`
- **State:** `available`
- **Internet Gateway Block Mode:** `off`

### 3.2 Security Groups

#### `geoyield-firewall` (`sg-0bdcf62d14ad3c02b`)
Configured firewall rules attached to `Geo-Yield-Server`:

| Port Range | Protocol | Source CIDR | Purpose |
| :--- | :--- | :--- | :--- |
| **22** | TCP | `0.0.0.0/0` | SSH remote management |
| **80** | TCP | `0.0.0.0/0` | HTTP standard ingress |
| **443** | TCP | `0.0.0.0/0` | HTTPS secure ingress |
| **8080** | TCP | `0.0.0.0/0` | FastAPI application backend / proxy endpoint |
| **5432** | TCP | `185.193.174.197/32` | PostgreSQL database access (IP-restricted) |

#### `default` (`sg-077b2f6ecbf0f6e55`)
- Standard AWS VPC default security group.

---

## 4. Object Storage (Amazon S3)

| Bucket Name | Region | Description |
| :--- | :--- | :--- |
| **`geoyield-raw-data-2026`** | **`eu-south-2`** | Raw data assets, legal documents, and ETL pipeline storage |
| `geoyield-frontend` | `eu-north-1` | Static frontend hosting for Vue 3 client application |

---

## 5. Managed AWS Services Status (`eu-south-2`)

- **Amazon RDS (Relational Database Service):** `0` instances (PostgreSQL runs self-hosted directly on EC2 host).
- **AWS Lambda:** `0` serverless functions.
- **Amazon Cognito:** `0` user pools in `eu-south-2`.
- **Amazon ECR (Container Registry):** `0` container repositories.
- **Amazon CloudWatch Logs:** `0` log groups created in `eu-south-2`.

---

## 6. Global Edge Integration (Amazon CloudFront)

The global CloudFront CDN is actively wired to route traffic between S3 and the `eu-south-2` EC2 origin:

- **Distribution ID:** `E20TNUC7CKHU1I`
- **CloudFront Domain:** `d2yya2azx26rn0.cloudfront.net`
- **Comment:** `Frontend Vue para Geo-Yield-AI`
- **Routing Behaviors:**
  1. **Default Cache Behavior (`/*`)**: Routes to S3 origin `geoyield-frontend.s3.eu-north-1.amazonaws.com` with SPA 403 error fallback to `/index.html`.
  2. **API Path (`/api/*`)**: Proxies HTTP methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS`) to origin `geoyield-backend-api` at:
     ```text
     ec2-15-217-22-254.eu-south-2.compute.amazonaws.com:8080
     ```
     Protocol Policy: `http-only` on port `8080`.
