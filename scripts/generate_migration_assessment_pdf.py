"""
Script to generate the Geo-Yield-AI AWS Migration Assessment PDF Report.
Uses ReportLab Platypus engine for publication-grade layout and typography.
"""

import os
import sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, inch, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and draw total page count."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Running header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(
                40,
                A4[1] - 30,
                "Geo-Yield-AI — AWS Cloud Migration Assessment (RDS, EC2, S3/CloudFront)",
            )
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(40, A4[1] - 34, A4[0] - 40, A4[1] - 34)

        # Running footer (all pages)
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(40, 36, A4[0] - 40, 36)

        self.drawString(40, 24, "CONFIDENTIAL — Technical Architecture Assessment")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(A4[0] - 40, 24, page_text)
        self.restoreState()


def create_assessment_pdf(output_path: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=46,
        bottomMargin=46,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    primary_color = colors.HexColor("#0F172A")    # Slate 900
    brand_blue = colors.HexColor("#0284C7")       # Sky 600
    dark_blue = colors.HexColor("#0369A1")        # Sky 700
    text_dark = colors.HexColor("#1E293B")        # Slate 800
    text_muted = colors.HexColor("#475569")       # Slate 600
    bg_light = colors.HexColor("#F8FAFC")         # Slate 50
    border_color = colors.HexColor("#CBD5E1")     # Slate 300

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=primary_color,
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=dark_blue,
        spaceAfter=12,
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=primary_color,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=dark_blue,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=text_dark,
        spaceAfter=6,
    )

    body_bold = ParagraphStyle(
        "Body_Bold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    bullet_style = ParagraphStyle(
        "Bullet_Custom",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3,
    )

    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.8,
        leading=10.5,
        textColor=text_dark,
    )

    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=table_cell,
        fontName="Helvetica-Bold",
    )

    meta_label = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=10,
        textColor=text_muted,
    )

    meta_val = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=primary_color,
    )

    callout_text = ParagraphStyle(
        "CalloutText",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0C4A6E"),
    )

    story = []

    # -------------------------------------------------------------------------
    # HEADER BANNER & METADATA
    # -------------------------------------------------------------------------
    story.append(Paragraph("Geo-Yield-AI — AWS Migration Assessment", title_style))
    story.append(
        Paragraph(
            "Production Architecture: Amazon RDS (PostgreSQL + PostGIS + pgvector), Amazon EC2 (FastAPI), & S3 + CloudFront (Vue 3)",
            subtitle_style,
        )
    )

    meta_data = [
        [
            Paragraph("Target Region:", meta_label),
            Paragraph("<b>eu-central-1</b> (Frankfurt) / eu-west-1", meta_val),
            Paragraph("Date:", meta_label),
            Paragraph("October 2026", meta_val),
        ],
        [
            Paragraph("Database Stack:", meta_label),
            Paragraph("RDS PostgreSQL 18 (PostGIS 3 + pgvector)", meta_val),
            Paragraph("Backend Compute:", meta_label),
            Paragraph("Amazon EC2 (t4g.small / Graviton3)", meta_val),
        ],
        [
            Paragraph("Frontend Delivery:", meta_label),
            Paragraph("Amazon S3 + CloudFront (OAC / SPA)", meta_val),
            Paragraph("AI / Vector RAG:", meta_label),
            Paragraph("Amazon Bedrock (Titan V2 - 1024d)", meta_val),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[80, 180, 85, 170])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg_light),
                ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 1. EXECUTIVE SUMMARY
    # -------------------------------------------------------------------------
    story.append(Paragraph("1. Executive Summary & Strategic Objectives", h1_style))
    story.append(
        Paragraph(
            "Geo-Yield-AI combines spatial sociodemographic analytics with an artificial intelligence "
            "legal assistant (RAG) specialized in Barcelona municipal urban planning (Pla General Metropolità). "
            "The project currently operates locally via Docker Compose. This assessment formulates the definitive "
            "engineering strategy to migrate the application into a highly available, secure, and cost-efficient "
            "production environment in <b>Amazon Web Services (AWS)</b>.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "The proposed architecture establishes a strict separation of concerns: persistent spatial and vector data "
            "are delegated to a managed <b>Amazon RDS for PostgreSQL</b> instance, the core FastAPI backend and Server-Sent "
            "Events (SSE) engine run on an optimized <b>Amazon EC2 Graviton3</b> instance, and the Vue 3 single-page application "
            "is delivered globally through <b>Amazon S3 and CloudFront</b> edge caching.",
            body_style,
        )
    )

    # Callout Box
    callout_data = [[
        Paragraph(
            "<b>Key Architectural Principle: Zero Plaintext Credentials.</b> By running the backend on EC2 with an attached "
            "<b>IAM Instance Profile</b>, the API invokes Amazon Bedrock (Titan Text Embeddings V2 & Reranker) and streams logs "
            "to Amazon CloudWatch through automatically rotated temporary AWS STS credentials, removing static API keys.",
            callout_text,
        )
    ]]
    callout_box = Table(callout_data, colWidths=[515])
    callout_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F9FF")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#7DD3FC")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(callout_box)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------------------
    # 2. ARCHITECTURE TOPOLOGY
    # -------------------------------------------------------------------------
    story.append(Paragraph("2. End-to-End AWS Target Architecture", h1_style))

    arch_rows = [
        [
            Paragraph("Layer", table_header),
            Paragraph("AWS Service & Component", table_header),
            Paragraph("Configuration & Specifications", table_header),
            Paragraph("Operational Responsibilities", table_header),
        ],
        [
            Paragraph("<b>Edge / CDN</b>", table_cell_bold),
            Paragraph("Amazon CloudFront", table_cell),
            Paragraph("HTTPS (port 443), TLS 1.3, Origin Access Control (OAC), SPA Fallback (403/404 -> /index.html 200 OK)", table_cell),
            Paragraph("Global SSL termination, edge caching, static asset distribution, and optional /api/* proxying to EC2.", table_cell),
        ],
        [
            Paragraph("<b>Frontend</b>", table_cell_bold),
            Paragraph("Amazon S3 (Private Bucket)", table_cell),
            Paragraph("Standard S3 Bucket with Block Public Access enabled; read policy granted strictly to CloudFront OAC Service Principal.", table_cell),
            Paragraph("Hosts compiled Vue 3 / Vite assets (HTML, vanilla JS, CSS, SVG icons). Zero server maintenance.", table_cell),
        ],
        [
            Paragraph("<b>Backend API</b>", table_cell_bold),
            Paragraph("Amazon EC2 (ARM64 / Graviton3)", table_cell),
            Paragraph("<code>t4g.small</code> (2 vCPU, 2 GB RAM). Docker container running <code>deployment/Dockerfile</code> or systemd. Nginx reverse proxy.", table_cell),
            Paragraph("FastAPI orchestration, geocoding endpoints, PGM legal retriever, and SSE streaming (buffer disabled).", table_cell),
        ],
        [
            Paragraph("<b>Database</b>", table_cell_bold),
            Paragraph("Amazon RDS for PostgreSQL", table_cell),
            Paragraph("PostgreSQL 18 (e.g. 18.6), <code>db.t4g.small</code>, 20-50 GB gp3 storage. Extensions: <b>postgis</b> and <b>vector</b> (pgvector).", table_cell),
            Paragraph("Stores census data, commercial competitors, spatial layers, and 1024-dimensional legal chunk vectors.", table_cell),
        ],
        [
            Paragraph("<b>AI Services</b>", table_cell_bold),
            Paragraph("Amazon Bedrock", table_cell),
            Paragraph("Embeddings: <code>amazon.titan-embed-text-v2:0</code> (1024d)<br/>Rerank: <code>amazon.rerank-v1:0</code> (eu-central-1)", table_cell),
            Paragraph("Serverless inference invoked directly via Boto3 / SigV4 authentication without maintaining ML models on disk.", table_cell),
        ],
    ]
    arch_table = Table(arch_rows, colWidths=[65, 110, 180, 160])
    arch_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), dark_blue),
                ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, bg_light]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(arch_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 3. COMPONENT DEEP DIVE
    # -------------------------------------------------------------------------
    story.append(Paragraph("3. Deep Dive by Component", h1_style))

    story.append(Paragraph("3.1 Relational & Spatial Database (Amazon RDS for PostgreSQL)", h2_style))
    story.append(
        Paragraph(
            "• <b>Engine & Extension Parity:</b> RDS PostgreSQL 18 supports both <code>postgis</code> and <code>vector</code>. "
            "Before restoring data, the database parameter group and initial DDL must execute: "
            "<code>CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;</code>.<br/>"
            "• <b>Vector Space Upgrade:</b> In accordance with Alembic migration <code>0006_titan_embeddings_dim.py</code>, "
            "the <code>legal_chunks.embedding</code> column is configured as <code>vector(1024)</code> with an HNSW cosine index "
            "(<code>vector_cosine_ops</code>).<br/>"
            "• <b>Network Isolation:</b> RDS must be placed in a private DB Subnet Group across two availability zones with "
            "<code>PubliclyAccessible=false</code>. Inbound traffic on port 5432 is strictly permitted only from the EC2 security group.<br/>"
            "• <b>Data Migration:</b> Logical dump via <code>pg_dump --format=custom --no-owner --no-acl</code> from the local Docker "
            "container, followed by <code>pg_restore --verbose --exit-on-error</code> against the RDS target as detailed in the runbook.",
            body_style,
        )
    )

    story.append(Paragraph("3.2 Backend API & Streaming Server (Amazon EC2)", h2_style))
    story.append(
        Paragraph(
            "• <b>Compute Form Factor:</b> An AWS Graviton3 <code>t4g.small</code> instance running Linux. Graviton processors deliver "
            "up to 20% better price/performance for Python FastAPIs and mathematical/GIS libraries compared to standard x86.<br/>"
            "• <b>Reverse Proxy & SSE Compatibility:</b> Nginx (or Caddy) sits in front of FastAPI. Crucially, the endpoints "
            "<code>/api/reports/stream</code> and <code>/api/chat/informe/stream</code> transmit live token streams. Nginx must explicitly "
            "disable response buffering: <code>proxy_buffering off; proxy_cache off; proxy_read_timeout 300s;</code>.<br/>"
            "• <b>IAM Instance Profile:</b> The EC2 instance assumes an IAM role with policies for Amazon Bedrock "
            "(<code>bedrock:InvokeModel</code>) and CloudWatch Logs (<code>logs:PutLogEvents</code>).",
            body_style,
        )
    )

    story.append(Paragraph("3.3 Frontend Application (Amazon S3 + CloudFront)", h2_style))
    story.append(
        Paragraph(
            "• <b>Static Distribution:</b> The Vue 3 application built with Vite generates pure static assets (HTML/JS/CSS). "
            "Amazon S3 acts as the object store without public website hosting enabled.<br/>"
            "• <b>CloudFront with Origin Access Control (OAC):</b> Restricts S3 bucket access solely to the CloudFront distribution.<br/>"
            "• <b>Client-Side Routing:</b> Vue Router HTML5 history mode requires that non-file paths return <code>index.html</code>. "
            "A CloudFront custom error response is configured: HTTP 403/404 -> <code>/index.html</code> with HTTP 200 status.<br/>"
            "• <b>Unified Domain & CORS Elimination:</b> CloudFront can route <code>/api/*</code> to the EC2 backend and all other "
            "requests to S3. Both frontend and backend share the identical origin (domain), completely eliminating browser CORS errors.",
            body_style,
        )
    )

    story.append(Spacer(1, 6))

    # -------------------------------------------------------------------------
    # 4. NETWORKING, SECURITY & SGs
    # -------------------------------------------------------------------------
    story.append(Paragraph("4. Networking & Security Architecture", h1_style))

    sec_rows = [
        [
            Paragraph("Security Group", table_header),
            Paragraph("Direction", table_header),
            Paragraph("Protocol / Port", table_header),
            Paragraph("Source / Destination", table_header),
            Paragraph("Purpose", table_header),
        ],
        [
            Paragraph("<b>sg-backend</b><br/>(EC2 Instance)", table_cell_bold),
            Paragraph("Inbound<br/>Inbound<br/>Outbound", table_cell),
            Paragraph("TCP 80, 443<br/>TCP 22<br/>All traffic", table_cell),
            Paragraph("0.0.0.0/0 (or CloudFront)<br/>Admin IP / SSM Session<br/>0.0.0.0/0", table_cell),
            Paragraph("Accepts web traffic and SSE streams.<br/>Admin access via SSH or SSM.<br/>Outbound to RDS, Bedrock, and Internet.", table_cell),
        ],
        [
            Paragraph("<b>sg-database</b><br/>(RDS PostgreSQL)", table_cell_bold),
            Paragraph("Inbound<br/>Outbound", table_cell),
            Paragraph("TCP 5432<br/>None", table_cell),
            Paragraph("<b>sg-backend ONLY</b><br/>-", table_cell),
            Paragraph("Allows SQL queries strictly from the backend API. Zero public exposure.", table_cell),
        ],
    ]
    sec_table = Table(sec_rows, colWidths=[95, 55, 80, 135, 150])
    sec_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), dark_blue),
                ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, bg_light]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(sec_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 5. FINANCIAL PROJECTION & COSTS
    # -------------------------------------------------------------------------
    story.append(Paragraph("5. Sizing & Estimated Monthly Cost (eu-central-1)", h1_style))
    story.append(
        Paragraph(
            "Pricing based on official AWS EU (Frankfurt) standard commercial rates as of late 2026. "
            "Numbers reflect production MVP workload with moderate traffic.",
            body_style,
        )
    )

    cost_rows = [
        [
            Paragraph("AWS Resource", table_header),
            Paragraph("Dimension / Instance Class", table_header),
            Paragraph("Pricing Metric", table_header),
            Paragraph("Monthly Cost (EUR)", table_header),
        ],
        [
            Paragraph("<b>RDS PostgreSQL</b>", table_cell_bold),
            Paragraph("<code>db.t4g.small</code> (2 vCPU, 2 GB RAM, Single-AZ)", table_cell),
            Paragraph("~$0.0416/hr + 20 GB gp3 ($0.115/GB)", table_cell),
            Paragraph("~ €31.00", table_cell_bold),
        ],
        [
            Paragraph("<b>EC2 Backend API</b>", table_cell_bold),
            Paragraph("<code>t4g.small</code> (2 vCPU, 2 GB RAM, 20 GB gp3 root)", table_cell),
            Paragraph("~$0.0168/hr + 20 GB gp3 ($0.08/GB)", table_cell),
            Paragraph("~ €14.50", table_cell_bold),
        ],
        [
            Paragraph("<b>Elastic IP Address</b>", table_cell_bold),
            Paragraph("1 Public IPv4 address assigned to EC2", table_cell),
            Paragraph("$0.005/hr in-use IPv4 charge", table_cell),
            Paragraph("~ €3.40", table_cell_bold),
        ],
        [
            Paragraph("<b>S3 Storage & Transfers</b>", table_cell_bold),
            Paragraph("< 1 GB static assets, GET/PUT requests", table_cell),
            Paragraph("Standard tier storage & API calls", table_cell),
            Paragraph("< €0.50", table_cell_bold),
        ],
        [
            Paragraph("<b>CloudFront CDN</b>", table_cell_bold),
            Paragraph("Edge caching, SSL termination, egress transfer", table_cell),
            Paragraph("Within 1 TB/month Always Free Tier", table_cell),
            Paragraph("€0.00 (Free Tier)", table_cell_bold),
        ],
        [
            Paragraph("<b>Bedrock & Observability</b>", table_cell_bold),
            Paragraph("Titan Text Embeddings V2 + CloudWatch logs", table_cell),
            Paragraph("$0.00002/1k tokens + log ingestion", table_cell),
            Paragraph("~ €3.00 – €5.00", table_cell_bold),
        ],
        [
            Paragraph("<b>TOTAL ESTIMATED MONTHLY SPEND</b>", table_cell_bold),
            Paragraph("Full Production Stack", table_cell_bold),
            Paragraph("On-Demand Rates Baseline", table_cell_bold),
            Paragraph("<b>~ €52.40 – €55.00 / month</b>", table_cell_bold),
        ],
    ]
    cost_table = Table(cost_rows, colWidths=[120, 165, 130, 100])
    cost_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), dark_blue),
                ("BOX", (0, 0), (-1, -1), 0.5, border_color),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, bg_light]),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E0F2FE")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(cost_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 6. IMPLEMENTATION ROADMAP
    # -------------------------------------------------------------------------
    story.append(Paragraph("6. Step-by-Step Migration Roadmap & Cutover Plan", h1_style))

    roadmap_steps = [
        "<b>Phase 1: AWS Foundation & Networking</b><br/>"
        "Create custom VPC with 2 public subnets (Internet Gateway) and 2 private subnets. "
        "Define <code>sg-backend</code> and <code>sg-database</code> security groups. "
        "Create IAM Instance Profile with <code>bedrock:InvokeModel</code> and CloudWatch write permissions.",

        "<b>Phase 2: Database Provisioning & Schema Restoration</b><br/>"
        "Launch RDS PostgreSQL 18. Enable <code>postgis</code> and <code>vector</code> extensions. "
        "Export local database with <code>pg_dump --format=custom --no-owner --no-acl -d geoyield -f geoyield.dump</code>. "
        "Restore into RDS via <code>pg_restore --verbose --exit-on-error</code>. Validate Alembic revision matches <code>0006</code>.",

        "<b>Phase 3: Backend EC2 Configuration</b><br/>"
        "Launch EC2 <code>t4g.small</code> instance. Attach the IAM Instance Profile. "
        "Deploy the backend using Docker (<code>deployment/Dockerfile</code>). Inject production <code>.env</code> with "
        "RDS <code>DATABASE_URL</code> (enforcing <code>sslmode=verify-full</code>). Setup Nginx reverse proxy with SSE streaming.",

        "<b>Phase 4: Frontend Delivery (S3 + CloudFront)</b><br/>"
        "Compile Vue 3 app with production API endpoint (<code>npm run build</code>). Create private S3 bucket and upload <code>dist/</code>. "
        "Create CloudFront distribution with Origin Access Control (OAC), ACM SSL certificate, and SPA error page routing.",

        "<b>Phase 5: Cutover & End-to-End Validation</b><br/>"
        "Execute sanity checks on <code>/health</code> and <code>/ready</code>. "
        "Verify spatial endpoints (district boundary calculations, competitor radius queries). "
        "Verify Bedrock RAG vector search and streaming legal generation (<code>/api/reports/stream</code>).",
    ]

    for step in roadmap_steps:
        story.append(Paragraph(f"• {step}", bullet_style))
        story.append(Spacer(1, 2))

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated: {output_path}")


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "docs/aws-migration-assessment.pdf"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    create_assessment_pdf(out_file)
