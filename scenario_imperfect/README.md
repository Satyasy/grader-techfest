# Skenario Pengujian Imperfect (Sengaja Salah) — TECHFEST 2026

Direktori ini memuat konfigurasi Terraform yang sengaja disuntikkan beberapa kesalahan arsitektur untuk memvalidasi sensitivitas deteksi dan pemberian penalti pada `grader_techfest2026.py`.

---

## 🎯 Daftar Kesalahan yang Disuntikkan:

1. **Missing S3 Gateway VPC Endpoint**:
   - `aws_vpc_endpoint.s3` dihilangkan.
   - **Target Dampak Grader**: Skor `A1.6_S3_Gateway_EP` menjadi **0.0 Poin** (seharusnya 1.0).

2. **Nama Database Tidak Sesuai Parameter Lomba**:
   - `db_name` diubah menjadi `techfest_database_salah` (bukan `techfest_final_db`).
   - **Target Dampak Grader**: Skor `C1.3_RDS_DB_Name` menjadi **0.0 Poin** (seharusnya 3.0).

3. **IAM Instance Profile Bukan LabRole**:
   - IAM Role diubah namanya menjadi `CustomAppRole` dan instance profile menjadi `CustomAppInstanceProfile` (tidak mengandung substring `LabRole` / `LabInstanceProfile`).
   - **Target Dampak Grader**: Skor `D1.1_LT_LabRole` menjadi **0.0 Poin** (seharusnya 5.0).

4. **EC2 Diberi Public IPv4 (Pelanggaran Kritis)**:
   - `associate_public_ip_address = true` pada Launch Template.
   - **Target Dampak Grader**:
     - Skor `D1.2_LT_No_Public_IP` menjadi **0.0 Poin** (seharusnya 5.0).
     - Terdeteksi Penalti Kritis `P.1_EC2_HAS_PUBLIC_IP` sebesar **-20.0 Poin**.

5. **Kapasitas ASG Tidak Sesuai Soal**:
   - Diatur `Min=2, Desired=2, Max=2` (seharusnya `Min=1, Desired=2, Max=3`).
   - **Target Dampak Grader**: Skor `E1.2_ASG_Capacity_Rules` turun ke nilai parsial **2.0 Poin** (seharusnya 4.0).

---

## 📊 Prediksi Perhitungan Skor Grader:
- **Total Poin Lulus Maksimum**: 100.00
- **Kehilangan Poin Komponen**: -16.00 (1.0 + 3.0 + 5.0 + 5.0 + 2.0)
- **Subtotal Poin**: 84.00
- **Penalti Kritis**: -20.00 (`P.1_EC2_HAS_PUBLIC_IP`)
- **Prediksi Skor Akhir di Grader**: **~64.00 / 100.00**

---

## 🚀 Cara Menjalankan Skenario Ini:

```bash
cd scenario_imperfect
terraform init
terraform apply
```

Setelah instance EC2 up dan healthy di Target Group, jalankan grader dari root workspace:
```bash
python grader_techfest2026.py
```
Periksa tabel terminal dan file `hasil_penilaian_cis.csv` untuk memastikan grader berhasil memotong nilai dan menampilkan baris peringatan penalti kritis `P.1_EC2_HAS_PUBLIC_IP`.
