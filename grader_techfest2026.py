import csv
import json
import base64
import requests
import boto3
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor
import sys
import io
import os
import re

# ReportLab untuk ekspor otomatis ke PDF profesional
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

# Pastikan output terminal mendukung UTF-8 pada Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

TARGET_CIDR_VPC = "10.20.0.0/16"
TARGET_SUBNETS = {
    "10.20.10.0/24": "Public Subnet A",
    "10.20.20.0/24": "Public Subnet B",
    "10.20.110.0/24": "Private Subnet A",
    "10.20.120.0/24": "Private Subnet B"
}
TARGET_DB_NAME = "techfest_final_db"
TARGET_DB_USER = "tf11_app"
TARGET_REPO = "techfest-11-v1"

COMPONENT_DEFINITIONS = {
    "A1.1": {"name": "Amazon VPC Target CIDR Block (10.20.0.0/16)", "max_score": 2.0, "expected": "VPC dengan CIDR 10.20.0.0/16"},
    "A1.2": {"name": "Public Subnet Redundansi Multi-AZ (Subnet A & B)", "max_score": 3.0, "expected": "2 Public Subnet di AZ berbeda (10.20.10.0/24 & 10.20.20.0/24)"},
    "A1.3": {"name": "Private Subnet Isolasi Multi-AZ (Subnet A & B)", "max_score": 3.0, "expected": "2 Private Subnet di AZ berbeda (10.20.110.0/24 & 10.20.120.0/24)"},
    "A1.4": {"name": "Internet Gateway Attachment ke VPC", "max_score": 3.0, "expected": "1 Internet Gateway terpasang aktif pada VPC"},
    "A1.5": {"name": "NAT Gateway Egress Subnet Privat (Maks 1 Unit)", "max_score": 3.0, "expected": "Tepat 1 NAT Gateway berstatus available"},
    "A1.6": {"name": "S3 Gateway VPC Endpoint pada Route Table Privat", "max_score": 1.0, "expected": "1 VPC Endpoint (Gateway) untuk layanan S3 terhubung ke RT Privat"},
    "B1.1": {"name": "Arsitektur 3-Tier Security Group (ALB, APP, RDS)", "max_score": 3.0, "expected": "3 SG terpisah: SG-ALB, SG-APP, SG-RDS"},
    "B1.2": {"name": "Inbound Security Group ALB (HTTP Port 80 Publik)", "max_score": 2.0, "expected": "Inbound TCP Port 80 dibuka ke 0.0.0.0/0"},
    "B1.3": {"name": "Chained Inbound SG EC2 App (Hanya dari SG ALB)", "max_score": 2.5, "expected": "Inbound TCP Port 80 hanya dari SG ALB"},
    "B1.4": {"name": "Chained Inbound SG RDS MySQL (Hanya dari SG App)", "max_score": 2.5, "expected": "Inbound TCP Port 3306 hanya dari SG APP"},
    "C1.1": {"name": "Amazon RDS MySQL Instance Status (Available)", "max_score": 3.0, "expected": "Status RDS Instance = 'available' (Engine MySQL Single-AZ)"},
    "C1.2": {"name": "Private RDS Subnet Group (Multi-AZ Subnets)", "max_score": 4.0, "expected": "PubliclyAccessible=False & DB Subnet Group minimal 2 AZ"},
    "C1.3": {"name": "Parameter Database RDS (DB: techfest_final_db, User: tf11_app)", "max_score": 3.0, "expected": "DB Name = 'techfest_final_db' & Master Username = 'tf11_app'"},
    "C1.4": {"name": "Amazon S3 Storage & Block Public Access (PAB)", "max_score": 5.0, "expected": "Bucket S3 private dengan 4 flag Block Public Access aktif"},
    "D1.1": {"name": "Launch Template IAM Profile (LabRole)", "max_score": 5.0, "expected": "Instance Profile mengandung 'LabRole' / 'LabInstanceProfile'"},
    "D1.2": {"name": "Isolasi Interface EC2 (Tanpa Public IPv4)", "max_score": 5.0, "expected": "AssociatePublicIpAddress = False di Launch Template"},
    "D1.3": {"name": "Bootstrap User Data (Clone Repository Resmi)", "max_score": 5.0, "expected": "Script User Data meng-clone repository 'novraepe/techfest-11-v1'"},
    "D1.4": {"name": "Security Group EC2 Aplikasi (Chained ke SG-APP)", "max_score": 5.0, "expected": "Launch Template terhubung ke Security Group SG-APP"},
    "E1.1": {"name": "Internet-Facing Application Load Balancer Multi-AZ", "max_score": 4.0, "expected": "ALB scheme internet-facing terpasang di minimal 2 AZ"},
    "E1.2": {"name": "Aturan Kapasitas Auto Scaling Group (1/2/3)", "max_score": 4.0, "expected": "Min=1, Desired=2, Max=3 terhubung ke Launch Template"},
    "E1.3": {"name": "Target Group Health Check Path (/up)", "max_score": 4.0, "expected": "Target Group protocol HTTP port 80 dengan path '/up'"},
    "E1.4": {"name": "Target Health Status ALB (Minimal 2 Target Healthy)", "max_score": 4.0, "expected": "Minimal 2 target EC2 berstatus 'healthy' di Target Group"},
    "E1.5": {"name": "Pengujian Fungsional HTTP Probe (200 OK) via ALB", "max_score": 4.0, "expected": "HTTP GET http://<ALB-DNS> merespon status 200 OK"},
    "F1.1": {"name": "Konektivitas Database Laravel & Migrasi Berjalan", "max_score": 5.0, "expected": "Halaman web tidak menampilkan error koneksi database/SQLSTATE"},
    "F1.2": {"name": "Integritas Aplikasi Production (APP_DEBUG=false)", "max_score": 5.0, "expected": "Tidak ada kebocoran debug Laravel (Ignition/Whoops)"},
    "G1.1": {"name": "Observability & CloudWatch Metric Alarm", "max_score": 10.0, "expected": "Minimal 1 CloudWatch Metric Alarm aktif untuk monitoring"}
}

PENALTY_DEFINITIONS = {
    "P.1": {"name": "EC2 Worker Memiliki Public IPv4", "penalty": -10.0, "desc": "Instance EC2 aplikasi ditemukan memiliki Public IP Address."},
    "P.2": {"name": "Database RDS Bersifat Publik (Internet Accessible)", "penalty": -10.0, "desc": "RDS MySQL diset PubliclyAccessible = True."},
    "P.3": {"name": "Bucket S3 Publik / Block Public Access Tidak Aktif", "penalty": -10.0, "desc": "S3 Bucket tidak mengaktifkan seluruh flag Block Public Access."},
    "P.4": {"name": "Mode Debug Aktif di Production (APP_DEBUG=true)", "penalty": -10.0, "desc": "Terdeteksi halaman debug Ignition/Whoops pada respon ALB."}
}

def sanitize_filename(name):
    """Membersihkan nama agar aman digunakan sebagai nama file."""
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', name.strip())
    return clean[:40] if clean else "peserta"

def load_participants():
    """
    Memuat kredensial peserta secara fleksibel:
    1. Membaca 'peserta.csv' jika tersedia (kolom: nama/email, access_key, secret_key, session_token, region).
    2. Fallback membaca '.env' jika peserta.csv tidak ada atau kosong.
    """
    participants = []
    csv_file = "peserta.csv"
    
    if os.path.exists(csv_file):
        try:
            with open(csv_file, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader, 1):
                    # Fleksibel: gunakan 'nama' atau 'email'
                    name = row.get('nama') or row.get('name') or row.get('email') or f"Peserta_{idx}"
                    email = row.get('email') or "-"
                    acc_key = row.get('access_key') or row.get('aws_access_key_id') or ""
                    sec_key = row.get('secret_key') or row.get('aws_secret_access_key') or ""
                    token = row.get('session_token') or row.get('aws_session_token') or ""
                    region = row.get('region') or "us-east-1"
                    
                    if acc_key.strip():
                        participants.append({
                            "id": f"SISWA-{idx:02d}",
                            "nama": name.strip(),
                            "email": email.strip(),
                            "access_key": acc_key.strip(),
                            "secret_key": sec_key.strip(),
                            "session_token": token.strip(),
                            "region": region.strip()
                        })
        except Exception as e:
            print(f"⚠️ Peringatan saat membaca '{csv_file}': {str(e)}")

    # Fallback ke .env jika peserta.csv kosong
    if not participants and os.path.exists(".env"):
        print("ℹ️ 'peserta.csv' kosong atau tidak ditemukan. Membaca dari file '.env'...")
        env_vars = {}
        try:
            with open(".env", mode='r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env_vars[k.strip()] = v.strip().strip('"').strip("'")
            
            # Cek apakah ada multi-akun di .env (misal SISWA_1_KEY, SISWA_2_KEY...)
            siswa_indices = set()
            for k in env_vars.keys():
                m = re.match(r'SISWA_(\d+)_(?:KEY|ACCESS_KEY)', k, re.IGNORECASE)
                if m:
                    siswa_indices.add(int(m.group(1)))
            
            if siswa_indices:
                for idx in sorted(siswa_indices):
                    name = env_vars.get(f"SISWA_{idx}_NAMA") or env_vars.get(f"SISWA_{idx}_NAME") or env_vars.get(f"SISWA_{idx}_EMAIL") or f"Siswa_{idx}"
                    email = env_vars.get(f"SISWA_{idx}_EMAIL") or "-"
                    acc_key = env_vars.get(f"SISWA_{idx}_KEY") or env_vars.get(f"SISWA_{idx}_ACCESS_KEY") or ""
                    sec_key = env_vars.get(f"SISWA_{idx}_SECRET") or env_vars.get(f"SISWA_{idx}_SECRET_KEY") or ""
                    token = env_vars.get(f"SISWA_{idx}_TOKEN") or env_vars.get(f"SISWA_{idx}_SESSION_TOKEN") or ""
                    region = env_vars.get(f"SISWA_{idx}_REGION") or "us-east-1"
                    if acc_key:
                        participants.append({
                            "id": f"SISWA-{idx:02d}",
                            "nama": name,
                            "email": email,
                            "access_key": acc_key,
                            "secret_key": sec_key,
                            "session_token": token,
                            "region": region
                        })
            else:
                # Cek akun standar AWS_ACCESS_KEY_ID tunggal
                acc_key = env_vars.get("AWS_ACCESS_KEY_ID")
                if acc_key:
                    participants.append({
                        "id": "SISWA-01",
                        "nama": env_vars.get("NAMA_PESERTA") or env_vars.get("EMAIL_PESERTA") or "Peserta Utama",
                        "email": env_vars.get("EMAIL_PESERTA") or "-",
                        "access_key": acc_key,
                        "secret_key": env_vars.get("AWS_SECRET_ACCESS_KEY", ""),
                        "session_token": env_vars.get("AWS_SESSION_TOKEN", ""),
                        "region": env_vars.get("AWS_DEFAULT_REGION", "us-east-1")
                    })
        except Exception as e:
            print(f"⚠️ Gagal membaca kredensial dari .env: {str(e)}")

    return participants

def generate_leaderboard_pdf(results, output_pdf_path="LEADERBOARD_TECHFEST_2026.pdf"):
    """Menghasilkan rekap peringkat juara (Leaderboard) resmi untuk juri dalam format PDF."""
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'LeadTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22,
        textColor=colors.HexColor('#0F172A'), alignment=1, spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'LeadSub', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14,
        textColor=colors.HexColor('#475569'), alignment=1, spaceAfter=14
    )
    header_cell = ParagraphStyle('HeadCell', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0F172A'), alignment=1)
    body_cell = ParagraphStyle('BodyCell', parent=styles['Normal'], fontName='Helvetica', fontSize=9, textColor=colors.HexColor('#1E293B'))
    score_cell = ParagraphStyle('ScoreCell', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=1)

    elements = [
        Paragraph("🏆 LEADERBOARD PENILAIAN JURI — TECHFEST 2026", title_style),
        Paragraph("Rekapitulasi Peringkat Nilai Akhir Peserta Cloud Computing AWS Academy Learner Lab", subtitle_style),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceAfter=12)
    ]

    table_data = [
        [Paragraph("<b>Peringkat</b>", header_cell), Paragraph("<b>Nama Peserta / Email</b>", header_cell), Paragraph("<b>Status</b>", header_cell), Paragraph("<b>Penalti Kritis</b>", header_cell), Paragraph("<b>Skor Akhir</b>", header_cell)]
    ]

    for rank, r in enumerate(results, 1):
        total = r["total_score"]
        sc_color = "#16A34A" if total >= 80 else ("#D97706" if total >= 60 else "#DC2626")
        
        # Trophy / Medali untuk Top 3
        rank_badge = f"🥇 Juara 1" if rank == 1 else (f"🥈 Juara 2" if rank == 2 else (f"🥉 Juara 3" if rank == 3 else f"#{rank}"))
        status_txt = "SANGAT BAIK" if total >= 85 else ("KOMPETEN" if total >= 65 else "BELUM KOMPETEN")
        pen_count = len(r.get("penalties", {}))
        pen_txt = f"{pen_count} Pelanggaran ({sum(r['penalties'].values()):.1f} Poin)" if pen_count > 0 else "0 (Aman)"

        table_data.append([
            Paragraph(f"<b>{rank_badge}</b>", body_cell),
            Paragraph(f"<b>{r['nama']}</b><br/><font size=7 color='#64748B'>{r.get('email', '')}</font>", body_cell),
            Paragraph(status_txt, body_cell),
            Paragraph(pen_txt, body_cell),
            Paragraph(f"<font color='{sc_color}'><b>{total:.2f}</b></font> / 100", score_cell)
        ])

    lead_table = Table(table_data, colWidths=[2.5 * cm, 7.5 * cm, 3.2 * cm, 3.5 * cm, 2.5 * cm])
    lead_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(lead_table)

    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#94A3B8'), spaceAfter=6))
    elements.append(Paragraph("Diterbitkan secara otomatis oleh CIS Techfest Evaluation Engine. Berkas evaluasi individual masing-masing siswa tersedia pada folder proyek.", ParagraphStyle('Foot', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#64748B'), alignment=1)))

    doc.build(elements)

def generate_pdf_report(report, output_pdf_path):
    """Menghasilkan dokumen PDF evaluasi individual resmi dengan ReportLab."""
    cid = report["id"]
    name = report["nama"]
    email = report.get("email", "-")
    eval_details = report["eval_details"]
    penalties = report["penalties"]
    total = report["total_score"]

    doc = SimpleDocTemplate(
        output_pdf_path, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22,
        textColor=colors.HexColor('#0F172A'), alignment=1, spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14,
        textColor=colors.HexColor('#475569'), alignment=1, spaceAfter=12
    )
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12, leading=16,
        textColor=colors.HexColor('#1E293B'), spaceBefore=10, spaceAfter=6
    )
    cell_text = ParagraphStyle('CellText', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor('#1E293B'))
    cell_code = ParagraphStyle('CellCode', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#0F172A'))
    cell_proof = ParagraphStyle('CellProof', parent=styles['Normal'], fontName='Courier', fontSize=7, leading=9, textColor=colors.HexColor('#334155'))

    elements = [
        Paragraph("TECHFEST 2026 — LEMBAR HASIL EVALUASI PESERTA", title_style),
        Paragraph("AWS Academy Learner Lab Cloud Computing Competition • Automated Evaluation Engine", subtitle_style),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceAfter=8)
    ]

    score_color = colors.HexColor('#16A34A') if total >= 80 else (colors.HexColor('#D97706') if total >= 60 else colors.HexColor('#DC2626'))
    info_data = [
        [
            Paragraph(f"<b>Nama Peserta:</b> {name}<br/><b>Email:</b> {email}<br/><b>Region AWS:</b> {report.get('region', 'us-east-1')}", cell_text),
            Paragraph(f"<font size=9><b>TOTAL SKOR AKHIR</b></font><br/><font size=20 color='{score_color.hexval()}'><b>{total:.2f}</b></font> <font size=11 color='#64748B'>/ 100.00</font>", ParagraphStyle('ScoreCard', parent=cell_text, alignment=1))
        ]
    ]
    info_table = Table(info_data, colWidths=[11.5 * cm, 6.0 * cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#F1F5F9')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 8))

    # Section 1: Ringkasan Nilai Komponen
    elements.append(Paragraph("1. Ringkasan Skor Evaluasi Komponen Teknis", section_heading))
    summary_data = [
        [Paragraph("<b>Kode</b>", cell_code), Paragraph("<b>Komponen Evaluasi</b>", cell_code), Paragraph("<b>Status</b>", cell_code), Paragraph("<b>Bobot</b>", cell_code), Paragraph("<b>Skor</b>", cell_code)]
    ]

    for code, item in COMPONENT_DEFINITIONS.items():
        det = eval_details.get(code, {})
        sc = det.get("score", 0.0)
        max_sc = item["max_score"]
        status_txt = "LULUS" if sc >= max_sc else ("PARSIAL" if sc > 0 else "GAGAL")
        st_color = "#16A34A" if sc >= max_sc else ("#D97706" if sc > 0 else "#DC2626")

        summary_data.append([
            Paragraph(f"<b>{code}</b>", cell_code),
            Paragraph(item["name"], cell_text),
            Paragraph(f"<font color='{st_color}'><b>{status_txt}</b></font>", cell_text),
            Paragraph(f"{max_sc:.1f}", cell_text),
            Paragraph(f"<b>{sc:.1f}</b>", cell_code)
        ])

    sum_table = Table(summary_data, colWidths=[1.5 * cm, 10.5 * cm, 2.0 * cm, 1.7 * cm, 1.8 * cm])
    sum_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 3.5),
    ]))
    elements.append(sum_table)

    # Section 2: Penalti Kritis
    if penalties:
        elements.append(Paragraph("2. Penalti Kritis Terdeteksi (Critical Violations)", section_heading))
        penalty_data = [
            [Paragraph("<b>Kode</b>", cell_code), Paragraph("<b>Jenis Pelanggaran</b>", cell_code), Paragraph("<b>Penalti</b>", cell_code), Paragraph("<b>Bukti Diagnosa AWS</b>", cell_code)]
        ]
        for p_code, p_val in penalties.items():
            p_def = PENALTY_DEFINITIONS.get(p_code, {"name": p_code, "desc": ""})
            penalty_data.append([
                Paragraph(f"<font color='#DC2626'><b>{p_code}</b></font>", cell_code),
                Paragraph(f"<b>{p_def['name']}</b>", cell_text),
                Paragraph(f"<font color='#DC2626'><b>{p_val:.1f} Poin</b></font>", cell_code),
                Paragraph(p_def['desc'], cell_proof)
            ])
        pen_table = Table(penalty_data, colWidths=[1.8 * cm, 5.5 * cm, 2.7 * cm, 7.5 * cm])
        pen_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FEE2E2')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#F87171')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#FECACA')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(pen_table)

    # Section 3: Rincian Bukti Audit Aktual AWS (Evidence Proof)
    elements.append(Paragraph("3. Rincian Bukti Audit Aktual AWS (Evidence & Confidence Proof)", section_heading))
    proof_data = [
        [Paragraph("<b>Kode</b>", cell_code), Paragraph("<b>Komponen Evaluasi</b>", cell_code), Paragraph("<b>Status</b>", cell_code), Paragraph("<b>Ekspektasi Soal</b>", cell_code), Paragraph("<b>Bukti Aktual AWS / Diagnosa</b>", cell_code)]
    ]

    for code, item in COMPONENT_DEFINITIONS.items():
        det = eval_details.get(code, {})
        sc = det.get("score", 0.0)
        max_sc = item["max_score"]
        status_txt = "LULUS" if sc >= max_sc else ("PARSIAL" if sc > 0 else "GAGAL")
        st_color = "#16A34A" if sc >= max_sc else ("#D97706" if sc > 0 else "#DC2626")
        expected = item["expected"]
        proof = det.get("proof", "Tidak ada bukti terdeteksi")

        proof_data.append([
            Paragraph(f"<b>{code}</b>", cell_code),
            Paragraph(item["name"], cell_text),
            Paragraph(f"<font color='{st_color}'><b>{status_txt}</b></font>", cell_text),
            Paragraph(expected, cell_text),
            Paragraph(proof, cell_proof)
        ])

    proof_table = Table(proof_data, colWidths=[1.3 * cm, 4.5 * cm, 1.7 * cm, 4.0 * cm, 6.0 * cm])
    proof_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(proof_table)

    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#94A3B8'), spaceAfter=4))
    elements.append(Paragraph("Dokumen evaluasi ini digenerate secara otomatis oleh CIS Techfest Evaluation Engine untuk TECHFEST 2026 Cloud Computing.", ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#64748B'), alignment=1)))

    doc.build(elements)

def generate_markdown_report(report, output_path):
    name = report["nama"]
    eval_details = report["eval_details"]
    penalties = report["penalties"]
    total = report["total_score"]

    md = [
        f"# 📊 Laporan Audit & Penilaian Evaluasi — TECHFEST 2026",
        f"\n> **Nama Peserta**: `{name}`  \n> **Email**: `{report.get('email', '-')}`  \n> **Waktu Audit**: `2026-11-04`  \n> **Total Skor Akhir**: **{total:.2f} / 100.00 Poin**\n",
        f"---\n",
        f"## 1. Ringkasan Skor Evaluasi",
        f"| Kode | Komponen Evaluasi | Status | Bobot | Skor |",
        f"| :---: | :--- | :---: | :---: | :---: |"
    ]

    for code, item in COMPONENT_DEFINITIONS.items():
        det = eval_details.get(code, {})
        score = det.get("score", 0.0)
        status_badge = "[x] LULUS" if score >= item["max_score"] else ("[~] PARSIAL" if score > 0 else "[ ] GAGAL")
        md.append(f"| **{code}** | {item['name']} | `{status_badge}` | {item['max_score']:.1f} Poin | **{score:.1f} Poin** |")

    md.append(f"\n## 2. Penalti Kritis Terdeteksi")
    if penalties:
        md.append(f"| Kode | Jenis Pelanggaran | Pengurangan Skor | Bukti Diagnosa |")
        md.append(f"| :---: | :--- | :---: | :--- |")
        for p_code, p_val in penalties.items():
            p_def = PENALTY_DEFINITIONS.get(p_code, {"name": p_code, "desc": ""})
            md.append(f"| 🚨 **{p_code}** | {p_def['name']} | **{p_val:.1f} Poin** | {p_def['desc']} |")
    else:
        md.append(f"✅ **Tidak ada penalti kritis terdeteksi.** Seluruh parameter keamanan dipatuhi (0.0 Poin).\n")

    md.append(f"\n## 3. Rincian Bukti Audit Aktual AWS (Evidence & Confidence Proof)")
    md.append(f"| Kode | Komponen | Status | Ekspektasi Soal | Bukti Aktual AWS / Diagnosa |")
    md.append(f"| :---: | :--- | :---: | :--- | :--- |")

    for code, item in COMPONENT_DEFINITIONS.items():
        det = eval_details.get(code, {})
        score = det.get("score", 0.0)
        status_str = "[x] LULUS" if score >= item["max_score"] else ("[~] PARSIAL" if score > 0 else "[ ] GAGAL")
        expected = item["expected"]
        proof = det.get("proof", "Tidak ada data yang ditemukan")
        md.append(f"| **{code}** | {item['name']} | `{status_str}` | {expected} | `{proof}` |")

    if report["details"]:
        md.append(f"\n## 4. Catatan & Rekomendasi Juri")
        for d in report["details"]:
            md.append(f"- ⚠️ {d}")

    md.append(f"\n---\n*Dokumen ini diterbitkan secara otomatis oleh CIS Techfest Evaluation Engine.*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

def print_leaderboard_terminal(results):
    """Menampilkan tabel peringkat nilai akhir di terminal console."""
    print("\n" + "=" * 100)
    print("🏆 REKAPITULASI PERINGKAT JUARA (LEADERBOARD) TECHFEST 2026".center(100))
    print("=" * 100)
    print(f"┌───────┬──────────────────────────────────┬──────────────────────┬─────────────┬──────────────┐")
    print(f"│ Rank  │ {'Nama Peserta':<32} │ {'Email':<20} │ {'Pelanggaran':<11} │ {'Skor Akhir':<12} │")
    print(f"├───────┼──────────────────────────────────┼──────────────────────┼─────────────┼──────────────┤")

    for rank, r in enumerate(results, 1):
        rank_str = f"🥇 #{rank}" if rank == 1 else (f"🥈 #{rank}" if rank == 2 else (f"🥉 #{rank}" if rank == 3 else f"#{rank}"))
        name_str = (r['nama'][:30] + '..') if len(r['nama']) > 32 else r['nama']
        email_str = (r.get('email', '-')[:18] + '..') if len(r.get('email', '-')) > 20 else r.get('email', '-')
        pen_cnt = f"{len(r.get('penalties', {}))} Penalti" if r.get('penalties') else "Aman (0)"
        score_str = f"{r['total_score']:.2f} / 100"

        print(f"│ {rank_str:<5} │ {name_str:<32} │ {email_str:<20} │ {pen_cnt:<11} │ {score_str:>12} │")

    print(f"└───────┴──────────────────────────────────┴──────────────────────┴─────────────┴──────────────┘\n")

def evaluate_candidate(c):
    name = c.get('nama') or c.get('name') or "Peserta"
    email = c.get('email') or "-"
    region = c.get('region', 'us-east-1').strip()
    
    report = {
        "id": c.get('id', 'SISWA'),
        "nama": name,
        "email": email,
        "region": region,
        "scores": {},
        "eval_details": {},
        "penalties": {},
        "total_score": 0.0,
        "details": []
    }

    try:
        session_kwargs = {"region_name": region}
        if c.get('access_key') and c['access_key'].strip():
            session_kwargs["aws_access_key_id"] = c['access_key'].strip()
        if c.get('secret_key') and c['secret_key'].strip():
            session_kwargs["aws_secret_access_key"] = c['secret_key'].strip()
        if c.get('session_token') and c['session_token'].strip():
            session_kwargs["aws_session_token"] = c['session_token'].strip()

        session = boto3.Session(**session_kwargs)
        ec2 = session.client('ec2')
        elbv2 = session.client('elbv2')
        autoscaling = session.client('autoscaling')
        rds = session.client('rds')
        s3 = session.client('s3')
        cloudwatch = session.client('cloudwatch')
    except Exception as e:
        report["details"].append(f"Auth Initialization Failed: {str(e)}")
        for code in COMPONENT_DEFINITIONS.keys():
            report["scores"][code] = 0.0
            report["eval_details"][code] = {"score": 0.0, "proof": f"Autentikasi gagal: {str(e)}"}
        return report

    def record_eval(code, score, proof):
        report["scores"][code] = score
        report["eval_details"][code] = {"score": score, "proof": proof}

    # =========================================================================
    # A. NETWORKING & ROUTING (15 Poin)
    # =========================================================================
    try:
        vpcs = ec2.describe_vpcs(Filters=[{'Name': 'cidr-block-association.cidr-block', 'Values': [TARGET_CIDR_VPC]}])['Vpcs']
        vpc_id = vpcs[0]['VpcId'] if vpcs else None
        if vpc_id:
            record_eval("A1.1", 2.0, f"VPC ID: {vpc_id} ({TARGET_CIDR_VPC})")
        else:
            record_eval("A1.1", 0.0, f"VPC dengan CIDR {TARGET_CIDR_VPC} tidak ditemukan")

        pub_subnets = []
        priv_subnets = []
        
        if vpc_id:
            subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['Subnets']
            for s in subnets:
                cidr = s['CidrBlock']
                if cidr in TARGET_SUBNETS:
                    if "Public" in TARGET_SUBNETS[cidr]:
                        pub_subnets.append(s)
                    else:
                        priv_subnets.append(s)

            pub_azs = list(set(s['AvailabilityZone'] for s in pub_subnets))
            pub_sub_info = [f"{s['CidrBlock']} ({s['SubnetId']})" for s in pub_subnets]
            if len(pub_subnets) >= 2 and len(pub_azs) >= 2:
                record_eval("A1.2", 3.0, f"{len(pub_subnets)} Public Subnets di {len(pub_azs)} AZ: {', '.join(pub_sub_info)}")
            else:
                record_eval("A1.2", 0.0, f"Ditemukan {len(pub_subnets)} subnet publik di AZ: {pub_azs} (ekspektasi minimal 2 AZ berbeda)")

            priv_azs = list(set(s['AvailabilityZone'] for s in priv_subnets))
            priv_sub_info = [f"{s['CidrBlock']} ({s['SubnetId']})" for s in priv_subnets]
            if len(priv_subnets) >= 2 and len(priv_azs) >= 2:
                record_eval("A1.3", 3.0, f"{len(priv_subnets)} Private Subnets di {len(priv_azs)} AZ: {', '.join(priv_sub_info)}")
            else:
                record_eval("A1.3", 0.0, f"Ditemukan {len(priv_subnets)} subnet privat di AZ: {priv_azs} (ekspektasi minimal 2 AZ berbeda)")

            igws = ec2.describe_internet_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}])['InternetGateways']
            if igws:
                record_eval("A1.4", 3.0, f"IGW ID: {igws[0]['InternetGatewayId']} terpasang pada VPC {vpc_id}")
            else:
                record_eval("A1.4", 0.0, f"Tidak ada Internet Gateway yang terpasang pada VPC {vpc_id}")

            nats = ec2.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}, {'Name': 'state', 'Values': ['available']}])['NatGateways']
            if len(nats) == 1:
                record_eval("A1.5", 3.0, f"Tepat 1 NAT Gateway aktif: {nats[0]['NatGatewayId']} di subnet {nats[0]['SubnetId']}")
            elif len(nats) > 1:
                record_eval("A1.5", 1.5, f"Ditemukan {len(nats)} NAT Gateway (melebihi batas lab 1 unit)")
            else:
                record_eval("A1.5", 0.0, "Tidak ditemukan NAT Gateway berstatus available")

            endpoints = ec2.describe_vpc_endpoints(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['VpcEndpoints']
            s3_ep = [ep['VpcEndpointId'] for ep in endpoints if ep['ServiceName'].endswith('.s3') and ep['VpcEndpointType'] == 'Gateway']
            if s3_ep:
                record_eval("A1.6", 1.0, f"S3 Gateway Endpoint aktif: {s3_ep[0]} terasosiasi ke VPC {vpc_id}")
            else:
                record_eval("A1.6", 0.0, f"S3 Gateway VPC Endpoint tidak ditemukan di VPC {vpc_id}")
        else:
            for k in ["A1.2", "A1.3", "A1.4", "A1.5", "A1.6"]:
                record_eval(k, 0.0, "VPC tidak valid, pengecekan dilewati")
    except Exception as e:
        for k in ["A1.1", "A1.2", "A1.3", "A1.4", "A1.5", "A1.6"]:
            record_eval(k, 0.0, f"Error: {str(e)}")

    # =========================================================================
    # B. SECURITY GROUPS & POLICIES (10 Poin)
    # =========================================================================
    sg_alb_id, sg_app_id, sg_rds_id = None, None, None
    try:
        if vpc_id:
            all_sgs = ec2.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['SecurityGroups']
            for sg in all_sgs:
                name_lower = sg['GroupName'].lower()
                if 'alb' in name_lower: sg_alb_id = sg['GroupId']
                elif 'app' in name_lower: sg_app_id = sg['GroupId']
                elif 'rds' in name_lower or 'db' in name_lower: sg_rds_id = sg['GroupId']

            if sg_alb_id and sg_app_id and sg_rds_id:
                record_eval("B1.1", 3.0, f"3-Tier SG lengkap: ALB={sg_alb_id}, APP={sg_app_id}, RDS={sg_rds_id}")
            else:
                record_eval("B1.1", 0.0, f"SG tidak lengkap: ALB={sg_alb_id}, APP={sg_app_id}, RDS={sg_rds_id}")

            sg_alb_ok = False
            if sg_alb_id:
                alb_rules = [sg for sg in all_sgs if sg['GroupId'] == sg_alb_id][0]['IpPermissions']
                for r in alb_rules:
                    if r.get('FromPort') == 80 and any(ip.get('CidrIp') == '0.0.0.0/0' for ip in r.get('IpRanges', [])):
                        sg_alb_ok = True
            record_eval("B1.2", 2.0 if sg_alb_ok else 0.0, f"Inbound Port 80 terbuka ke 0.0.0.0/0 pada SG-ALB ({sg_alb_id})" if sg_alb_ok else f"SG-ALB ({sg_alb_id}) tidak mengizinkan inbound HTTP Port 80 dari 0.0.0.0/0")

            sg_app_ok = False
            if sg_app_id and sg_alb_id:
                app_rules = [sg for sg in all_sgs if sg['GroupId'] == sg_app_id][0]['IpPermissions']
                for r in app_rules:
                    if any(ug.get('GroupId') == sg_alb_id for ug in r.get('UserIdGroupPairs', [])):
                        sg_app_ok = True
            record_eval("B1.3", 2.5 if sg_app_ok else 0.0, f"SG-APP ({sg_app_id}) chained: Inbound hanya dari SG-ALB ({sg_alb_id})" if sg_app_ok else f"SG-APP ({sg_app_id}) tidak chained ke SG-ALB ({sg_alb_id})")

            sg_rds_ok = False
            if sg_rds_id and sg_app_id:
                rds_rules = [sg for sg in all_sgs if sg['GroupId'] == sg_rds_id][0]['IpPermissions']
                for r in rds_rules:
                    if r.get('FromPort') == 3306 and any(ug.get('GroupId') == sg_app_id for ug in r.get('UserIdGroupPairs', [])):
                        sg_rds_ok = True
            record_eval("B1.4", 2.5 if sg_rds_ok else 0.0, f"SG-RDS ({sg_rds_id}) chained: Inbound Port 3306 hanya dari SG-APP ({sg_app_id})" if sg_rds_ok else f"SG-RDS ({sg_rds_id}) tidak mengizinkan port 3306 dari SG-APP ({sg_app_id})")
        else:
            for k in ["B1.1", "B1.2", "B1.3", "B1.4"]:
                record_eval(k, 0.0, "VPC tidak valid, pengecekan dilewati")
    except Exception as e:
        for k in ["B1.1", "B1.2", "B1.3", "B1.4"]:
            record_eval(k, 0.0, f"Error: {str(e)}")

    # =========================================================================
    # C. MANAGED DATABASE (RDS) & OBJECT STORAGE (S3) (15 Poin)
    # =========================================================================
    try:
        db_instances = rds.describe_db_instances()['DBInstances']
        if db_instances:
            dbi = db_instances[0]
            db_id = dbi['DBInstanceIdentifier']
            db_status = dbi['DBInstanceStatus']
            engine = dbi.get('Engine', 'unknown')
            multi_az = dbi.get('MultiAZ', False)
            record_eval("C1.1", 3.0 if db_status == 'available' else 1.0, f"RDS ID: '{db_id}' | Engine: {engine} | Single-AZ (MultiAZ={multi_az}) | Status: {db_status}")
            
            subnets_in_dbsg = len(dbi.get('DBSubnetGroup', {}).get('Subnets', []))
            is_private = not dbi['PubliclyAccessible']
            record_eval("C1.2", 4.0 if (is_private and subnets_in_dbsg >= 2) else 0.0, f"RDS ID: '{db_id}' Private (PubliclyAccessible=False) dengan {subnets_in_dbsg} Subnet di DB Subnet Group" if (is_private and subnets_in_dbsg >= 2) else f"RDS ID: '{db_id}' PubliclyAccessible={dbi['PubliclyAccessible']}, Subnet DB={subnets_in_dbsg}")

            db_name_actual = dbi.get('DBName', '')
            master_user_actual = dbi.get('MasterUsername', '')
            if db_name_actual == TARGET_DB_NAME and master_user_actual == TARGET_DB_USER:
                record_eval("C1.3", 3.0, f"DB Name: '{db_name_actual}' & User: '{master_user_actual}' sesuai target soal")
            elif db_name_actual == TARGET_DB_NAME:
                record_eval("C1.3", 2.0, f"DB Name: '{db_name_actual}' sesuai, namun Master User '{master_user_actual}' != '{TARGET_DB_USER}'")
            else:
                record_eval("C1.3", 0.0, f"DB Name aktual '{db_name_actual}' != '{TARGET_DB_NAME}' (User: '{master_user_actual}')")

            if dbi['PubliclyAccessible']:
                report["penalties"]["P.2"] = -10.0
        else:
            record_eval("C1.1", 0.0, "Tidak ada instance RDS MySQL yang ditemukan")
            record_eval("C1.2", 0.0, "Instance RDS tidak ditemukan")
            record_eval("C1.3", 0.0, "Instance RDS tidak ditemukan")
    except Exception as e:
        record_eval("C1.1", 0.0, f"Error: {str(e)}")
        record_eval("C1.2", 0.0, f"Error: {str(e)}")
        record_eval("C1.3", 0.0, f"Error: {str(e)}")

    try:
        buckets = s3.list_buckets()['Buckets']
        techfest_buckets = [b['Name'] for b in buckets if 'techfest' in b['Name'] or 'tf11' in b['Name']]
        target_bucket = techfest_buckets[0] if techfest_buckets else (buckets[0]['Name'] if buckets else None)
        
        if target_bucket:
            pab = s3.get_public_access_block(Bucket=target_bucket)['PublicAccessBlockConfiguration']
            if all([pab['BlockPublicAcls'], pab['IgnorePublicAcls'], pab['BlockPublicPolicy'], pab['RestrictPublicBuckets']]):
                record_eval("C1.4", 5.0, f"Bucket S3 '{target_bucket}' Private (4/4 Block Public Access Aktif)")
            else:
                record_eval("C1.4", 0.0, f"Bucket S3 '{target_bucket}' memiliki proteksi BPA tidak lengkap")
                report["penalties"]["P.3"] = -10.0
        else:
            record_eval("C1.4", 0.0, "Bucket S3 Techfest tidak ditemukan")
    except Exception as e:
        record_eval("C1.4", 0.0, f"S3 Error: {str(e)}")

    # =========================================================================
    # D. LAUNCH TEMPLATE & COMPUTE BLUEPRINT (20 Poin)
    # =========================================================================
    try:
        lts = ec2.describe_launch_templates()['LaunchTemplates']
        if lts:
            lt = lts[0]
            lt_id = lt['LaunchTemplateId']
            lt_name = lt['LaunchTemplateName']
            lt_data = ec2.describe_launch_template_versions(LaunchTemplateId=lt_id, Versions=['$Latest'])['LaunchTemplateVersions'][0]['LaunchTemplateData']
            
            iam_profile = lt_data.get('IamInstanceProfile', {}).get('Arn', '') or lt_data.get('IamInstanceProfile', {}).get('Name', '')
            if ("LabRole" in iam_profile or "LabInstanceProfile" in iam_profile):
                record_eval("D1.1", 5.0, f"LT ID: {lt_id} ('{lt_name}') | Instance Profile: '{iam_profile}'")
            else:
                record_eval("D1.1", 0.0, f"LT ID: {lt_id} ('{lt_name}') | Instance profile '{iam_profile}' tidak mengandung LabRole / LabInstanceProfile")

            ni = lt_data.get('NetworkInterfaces', [])
            no_public_ip = True
            if ni and ni[0].get('AssociatePublicIpAddress') is True:
                no_public_ip = False
            record_eval("D1.2", 5.0 if no_public_ip else 0.0, f"LT ID: {lt_id} | AssociatePublicIpAddress = False (EC2 terisolasi)" if no_public_ip else f"LT ID: {lt_id} | AssociatePublicIpAddress = True (Pelanggaran: EC2 diberi Public IP)")

            user_data_raw = lt_data.get('UserData', '')
            if user_data_raw:
                user_data_decoded = base64.b64decode(user_data_raw).decode('utf-8', errors='ignore')
                record_eval("D1.3", 5.0 if TARGET_REPO in user_data_decoded else 0.0, f"LT ID: {lt_id} | User Data meng-clone repository resmi '{TARGET_REPO}'" if TARGET_REPO in user_data_decoded else f"LT ID: {lt_id} | Repository target '{TARGET_REPO}' tidak ditemukan di script User Data")
            else:
                record_eval("D1.3", 0.0, f"LT ID: {lt_id} | Script User Data kosong pada Launch Template")

            lt_sgs = lt_data.get('SecurityGroupIds', [])
            if not lt_sgs and ni:
                lt_sgs = ni[0].get('Groups', [])
            record_eval("D1.4", 5.0 if (sg_app_id and sg_app_id in lt_sgs) else 2.5, f"LT ID: {lt_id} | Terhubung ke SG-APP ({sg_app_id})" if (sg_app_id and sg_app_id in lt_sgs) else f"LT ID: {lt_id} | SG pada LT: {lt_sgs} (tidak cocok eksak dengan SG-APP {sg_app_id})")
        else:
            for k in ["D1.1", "D1.2", "D1.3", "D1.4"]:
                record_eval(k, 0.0, "Launch Template tidak ditemukan (Peserta mungkin membuat EC2 manual)")
    except Exception as e:
        for k in ["D1.1", "D1.2", "D1.3", "D1.4"]:
            record_eval(k, 0.0, f"Error: {str(e)}")

    # =========================================================================
    # E. APPLICATION LOAD BALANCER & AUTO SCALING (20 Poin)
    # =========================================================================
    alb_dns = None
    target_group_arn = None
    try:
        lbs = elbv2.describe_load_balancers()['LoadBalancers']
        alb = next((l for l in lbs if l['Scheme'] == 'internet-facing'), None)
        if alb:
            alb_dns = alb['DNSName']
            alb_arn = alb['LoadBalancerArn']
            alb_azs = [f"{az['ZoneName']} ({az['SubnetId']})" for az in alb['AvailabilityZones']]
            record_eval("E1.1", 4.0 if len(alb_azs) >= 2 else 2.0, f"ALB: {alb['LoadBalancerName']} | Scheme: internet-facing di {len(alb_azs)} AZ: {', '.join(alb_azs)}" if len(alb_azs) >= 2 else f"ALB: {alb['LoadBalancerName']} | Hanya berada di {len(alb_azs)} AZ: {alb_azs}")
        else:
            record_eval("E1.1", 0.0, "Tidak ada Load Balancer bertipe internet-facing yang ditemukan")

        asgs = autoscaling.describe_auto_scaling_groups()['AutoScalingGroups']
        if asgs:
            asg = asgs[0]
            asg_name = asg['AutoScalingGroupName']
            min_c = asg['MinSize']
            des_c = asg['DesiredCapacity']
            max_c = asg['MaxSize']
            
            asg_lt = asg.get('LaunchTemplate')
            asg_mixed_lt = asg.get('MixedInstancesPolicy', {}).get('LaunchTemplate', {}).get('LaunchTemplateSpecification')
            used_lt = asg_lt or asg_mixed_lt
            
            lt_audit_str = f"LT: {used_lt.get('LaunchTemplateId') or used_lt.get('LaunchTemplateName')} (v{used_lt.get('Version', '$Default')})" if used_lt else "TIDAK TERHUBUNG KE LAUNCH TEMPLATE"
            capacity_ok = (min_c == 1 and des_c == 2 and max_c == 3)
            
            if capacity_ok and used_lt:
                record_eval("E1.2", 4.0, f"ASG: '{asg_name}' | Kapasitas: Min={min_c}, Desired={des_c}, Max={max_c} | {lt_audit_str}")
            elif not used_lt:
                record_eval("E1.2", 0.0, f"ASG: '{asg_name}' | {lt_audit_str}")
            else:
                record_eval("E1.2", 2.0, f"ASG: '{asg_name}' | Kapasitas: Min={min_c}, Des={des_c}, Max={max_c} (ekspektasi: 1/2/3) | {lt_audit_str}")
            
            tg_arns = asg.get('TargetGroupARNs', [])
            target_group_arn = tg_arns[0] if tg_arns else None
        else:
            record_eval("E1.2", 0.0, "Auto Scaling Group tidak ditemukan")

        if target_group_arn:
            tg_resp = elbv2.describe_target_groups(TargetGroupArns=[target_group_arn])['TargetGroups'][0]
            tg_name = tg_resp['TargetGroupName']
            hc_path = tg_resp.get('HealthCheckPath', '')
            hc_proto = tg_resp.get('Protocol', '')
            hc_port = tg_resp.get('Port', '')
            
            record_eval("E1.3", 4.0 if (hc_path == '/up' and hc_proto == 'HTTP') else 2.0, f"TG: '{tg_name}' | Protocol: {hc_proto}:{hc_port} | HealthCheckPath: '{hc_path}' sesuai soal lomba" if (hc_path == '/up' and hc_proto == 'HTTP') else f"TG: '{tg_name}' | HealthCheckPath: '{hc_path}' (ekspektasi: '/up') | Protocol: {hc_proto}:{hc_port}")

            th = elbv2.describe_target_health(TargetGroupArn=target_group_arn)['TargetHealthDescriptions']
            healthy = [t for t in th if t['TargetHealth']['State'] == 'healthy']
            healthy_ids = [t['Target']['Id'] for t in healthy]
            all_target_info = [f"{t['Target']['Id']}:{t['TargetHealth']['State']}" for t in th]
            
            if len(healthy) >= 2:
                record_eval("E1.4", 4.0, f"TG: '{tg_name}' | Healthy: {len(healthy)}/{len(th)} ({', '.join(healthy_ids)})")
            elif len(healthy) == 1:
                record_eval("E1.4", 2.0, f"TG: '{tg_name}' | Hanya 1 target healthy: {', '.join(all_target_info)}")
            else:
                reasons = ", ".join([f"{t['Target']['Id']}:{t['TargetHealth']['State']} ({t['TargetHealth'].get('Reason','')})" for t in th])
                record_eval("E1.4", 0.0, f"TG: '{tg_name}' | 0 healthy. Status: {reasons if reasons else 'Tidak ada instance terdaftar'}")
        else:
            record_eval("E1.3", 0.0, "Target Group tidak terpasang ke Auto Scaling Group")
            record_eval("E1.4", 0.0, "Target Group tidak ditemukan")

    except Exception as e:
        for k in ["E1.1", "E1.2", "E1.3", "E1.4"]:
            record_eval(k, 0.0, f"Error: {str(e)}")

    # =========================================================================
    # F. FUNCTIONAL HTTP & HA/INTEGRITY TEST (10 Poin)
    # =========================================================================
    if alb_dns:
        try:
            res = requests.get(f"http://{alb_dns}", timeout=8)
            record_eval("E1.5", 4.0 if res.status_code == 200 else 0.0, f"HTTP GET http://{alb_dns} -> Status {res.status_code}")
            
            body = res.text
            record_eval("F1.1", 5.0 if ("SQLSTATE" not in body and "Database connection error" not in body and res.status_code == 200) else 0.0, "Koneksi database Laravel bekerja normal (CRUD view peserta tampil)" if ("SQLSTATE" not in body and "Database connection error" not in body and res.status_code == 200) else "Terdeteksi indikasi error database atau HTTP non-200")

            if "Ignition" in body or "APP_DEBUG=true" in body or "Whoops" in body:
                report["penalties"]["P.4"] = -10.0
                record_eval("F1.2", 0.0, "Leak debugging terdeteksi (Ignition/Whoops)")
            else:
                record_eval("F1.2", 5.0, "Integritas aplikasi production bersih (APP_DEBUG=false)")

        except Exception as e:
            for k in ["E1.5", "F1.1", "F1.2"]:
                record_eval(k, 0.0, f"Koneksi timeout/gagal: {str(e)}")
    else:
        for k in ["E1.5", "F1.1", "F1.2"]:
            record_eval(k, 0.0, "DNS ALB tidak tersedia")

    # Cek Pelanggaran Kritis: Instance Memiliki Public IPv4
    try:
        app_instances = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])['Reservations']
        public_instances = []
        for resv in app_instances:
            for inst in resv['Instances']:
                pub_ip = inst.get('PublicIpAddress')
                if pub_ip:
                    public_instances.append(f"{inst['InstanceId']} ({pub_ip})")
        if public_instances:
            report["penalties"]["P.1"] = -10.0
            PENALTY_DEFINITIONS["P.1"]["desc"] = f"Ditemukan Public IP pada worker: {', '.join(public_instances)}"
    except Exception:
        pass

    # =========================================================================
    # G. OBSERVABILITY (10 Poin Otomatis dari 15 Poin Bagian B Soal Lomba)
    # =========================================================================
    try:
        alarms = cloudwatch.describe_alarms()['MetricAlarms']
        if alarms:
            alarm_names = [f"'{a['AlarmName']}' ({a['MetricName']}>={a.get('Threshold',0)})" for a in alarms]
            record_eval("G1.1", 10.0, f"CloudWatch Metric Alarm aktif ({len(alarms)}): {', '.join(alarm_names)}")
        else:
            record_eval("G1.1", 0.0, "Tidak ada CloudWatch Metric Alarm yang aktif")
    except Exception as e:
        record_eval("G1.1", 0.0, f"CloudWatch Error: {str(e)}")

    subtotal = sum(report["scores"].values())
    total_penalty = sum(report["penalties"].values())
    report["total_score"] = max(0.0, subtotal + total_penalty)

    return report

def main():
    participants = load_participants()
    if not participants:
        print("❌ Error: Tidak ada data peserta ditemukan pada 'peserta.csv' maupun '.env'!")
        print("💡 Silakan isi file 'peserta.csv' dengan format: nama, email, access_key, secret_key, session_token, region")
        return

    output_summary = "hasil_penilaian_cis.csv"
    output_leaderboard_pdf = "LEADERBOARD_TECHFEST_2026.pdf"

    print(f"\n🚀 Memulai evaluasi batch {len(participants)} akun peserta AWS Academy secara simultan (Parallel Engine)...")
    print(f"⚡ Menggunakan ThreadPoolExecutor (8 Worker concurrent)\n")

    # Eksekusi paralel menilai 10+ siswa sekaligus
    with ThreadPoolExecutor(max_workers=8) as executor:
        raw_results = list(executor.map(evaluate_candidate, participants))

    # SORTIR HASIL DARI NILAI TERBESAR KE TERKECIL (DESCENDING)
    results = sorted(raw_results, key=lambda x: x["total_score"], reverse=True)

    # 1. Tampilkan tabel Leaderboard di Terminal Console
    print_leaderboard_terminal(results)

    # 2. Cetak Berkas Leaderboard PDF Resmi Rekapitulasi Juri
    try:
        generate_leaderboard_pdf(results, output_leaderboard_pdf)
        print(f"🏆 Rekap Leaderboard Juara PDF berhasil dibuat: '{output_leaderboard_pdf}'")
    except Exception as e:
        print(f"⚠️ Gagal membuat PDF Leaderboard: {str(e)}")

    # 3. Cetak PDF & MD Evaluasi Individual Mandiri untuk Masing-Masing Siswa
    print("\n📄 Menghasilkan berkas evaluasi individual per peserta:")
    for rank, r in enumerate(results, 1):
        clean_name = sanitize_filename(r["nama"])
        pdf_file = f"evaluasi_{clean_name}.pdf"
        md_file = f"evaluasi_{clean_name}.md"

        try:
            generate_pdf_report(r, pdf_file)
            print(f"   [Rank #{rank}] {r['nama']} -> '{pdf_file}' (Skor: {r['total_score']:.2f})")
        except Exception as e:
            print(f"   ⚠️ Gagal membuat PDF untuk {r['nama']}: {str(e)}")

        generate_markdown_report(r, md_file)

    # 4. Ekspor ke CSV Rekapitulasi Juri (Tersortir dari Nilai Tertinggi)
    with open(output_summary, mode='w', newline='', encoding='utf-8') as out:
        fieldnames = ["peringkat", "nama", "email", "total_score", "penalties_applied", "scoring_breakdown", "notes"]
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        
        for rank, r in enumerate(results, 1):
            writer.writerow({
                "peringkat": rank,
                "nama": r["nama"],
                "email": r.get("email", "-"),
                "total_score": round(r["total_score"], 2),
                "penalties_applied": json.dumps(r["penalties"]),
                "scoring_breakdown": json.dumps(r["scores"]),
                "notes": " | ".join(r["details"])
            })

    print(f"\n✅ Selesai! Seluruh rekapan ('{output_leaderboard_pdf}' & '{output_summary}') siap digunakan juri.\n")

if __name__ == '__main__':
    main()
