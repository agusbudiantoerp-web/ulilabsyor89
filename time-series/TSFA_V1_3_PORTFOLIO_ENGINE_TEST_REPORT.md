# TSFA Dual Market V1.3 - Portfolio Engine Test Report

Tanggal pengujian: 13 November 2026

## 1. Ruang Lingkup
Pengujian lokal terhadap Portfolio Engine V1.3, integrasi upload workbook, perhitungan portofolio, dashboard Streamlit, dan ekspor Excel.

File engine utama: `tsfa_portfolio_engine.py`
File aplikasi: `TSFA_Dual_Market_V1_3.py`

## 2. Perubahan Kode
- Validasi saldo kas sebelum memproses transaksi WITHDRAWAL.
- Validasi agar pajak DIVIDEND dan INTEREST tidak melebihi Amount.
- Mempertahankan skala persentase internal 0-100 untuk Unrealized_PnL_Pct dan Weight_Pct.
- Menambahkan format worksheet ekspor Excel: header, freeze panes, autofilter, tanggal, persentase, angka, dan lebar kolom.

## 3. Hasil Pengujian Perhitungan
- BUY dan SELL: lulus.
- Moving weighted-average cost: lulus.
- Perhitungan realized dan unrealized P&L: lulus.
- CASH_FLOW deposit, withdrawal, dividend, dan tax: lulus.
- Penolakan withdrawal melebihi saldo: lulus.
- Penolakan pajak melebihi dividend atau interest: lulus.
- Pengujian transaksi multi-ticker: lulus.
- Penolakan BUY tanpa saldo kas cukup: lulus.
- Penolakan SELL melebihi saham tersedia: lulus.

## 4. Hasil Validasi Workbook
Delapan skenario workbook tidak valid berhasil ditolak:
1. Sheet wajib hilang.
2. Ticker HOLDING kosong.
3. Opening quantity tidak valid.
4. Currency bukan IDR.
5. Ticker HOLDING duplikat.
6. Baris CASH duplikat.
7. As_Of_Date tidak konsisten.
8. Kolom wajib hilang.

## 5. Integrasi Streamlit
Pengujian lokal membuktikan:
- Upload workbook pertama menghasilkan 100 saham BBRI.
- Upload workbook kedua menghasilkan 200 saham BBRI.
- Mengganti kembali workbook mengembalikan angka sesuai file yang diunggah.
- Perhitungan ulang dan pembaruan harga pasar bekerja.
- Dashboard menampilkan ringkasan portofolio, risiko, konsentrasi, alokasi, sektor, dan stress test.

## 6. Ekspor Excel
Pengujian ekspor menghasilkan 13 worksheet:
- HOLDINGS
- ANALYSIS_RESULTS
- PORTFOLIO_SUMMARY
- VALIDATION_NOTES
- RISK_ANALYSIS
- RISK_CONTRIBUTION
- CORRELATION_MATRIX
- TARGET_ALLOCATION
- REBALANCING_ANALYSIS
- SECTOR_EXPOSURE
- SECTOR_HOLDINGS
- MARKET_STRESS
- SECTOR_STRESS

Pemeriksaan format angka, persentase, tanggal, header, autofilter, dan freeze panes berhasil.
Rekonsiliasi hasil dashboard dan workbook ekspor untuk pengujian BBRI 200 saham berhasil.

## 7. Pengujian Multi-Ticker
Skenario BBRI dan TLKM dengan transaksi BUY/SELL berhasil dihitung. Saldo kas, jumlah saham, average cost, realized P&L, market value, dan unrealized P&L sesuai hasil perhitungan yang diharapkan.

## 8. Batasan dan Catatan
- Pengujian menggunakan workbook sintetis, bukan validasi menyeluruh atas seluruh kemungkinan data transaksi nyata.
- Pengujian risiko dengan satu saham tidak membuktikan kualitas diversifikasi portofolio.
- Tahap awal V1.3 dibatasi pada saham Indonesia dalam IDR.
- Pengujian ini bukan audit keamanan menyeluruh atau jaminan keamanan sistem produksi.
- Belum merupakan persetujuan untuk deploy produksi.

## 9. Status Teknis
- Python compile check: lulus.
- Git diff whitespace check: lulus.
- Dashboard lokal: diuji.
- Excel export: diuji.
- Commit: belum dilakukan.
- Push: belum dilakukan.
- Deploy dari perubahan terakhir: belum dilakukan.
- V1.2: dipertahankan tanpa perubahan dalam tahap ini.

## 10. File yang Perlu Dijaga
File kode utama yang berubah:
- `time-series/tsfa_portfolio_engine.py`

File pengujian dan backup lokal tidak boleh ikut commit secara tidak sengaja:
- `projects_BACKUP.json`
- `TSFA_FORMAT_TEST_OUTPUT.xlsx`
- `TSFA_FULL_FORMAT_TEST_OUTPUT.xlsx`
- `TSFA_TEST_UPLOAD.xlsx`
- `TSFA_TEST_UPLOAD_V2.xlsx`
- File backup engine lokal.

---

Laporan ini mencatat hasil pengujian yang telah dilakukan pada lingkungan lokal, bukan sertifikasi atau audit produksi.
