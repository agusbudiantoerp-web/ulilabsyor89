import pandas as pd
import pytest

from broker_statement_import import normalize_broker_statement


def test_normalizes_indonesian_headers_and_decimal_conventions():
    csv_text = (
        "Tanggal Transaksi;Jenis Transaksi;Kode Saham;Jumlah Saham;Harga;Nilai Transaksi\n"
        "25/11/2026;BELI;BBCA;1.000;9.250,50;9.250.500,00\n"
        "26/11/2026;JUAL;TLKM;200;3.100,00;620.000,00\n"
    )
    result = normalize_broker_statement(csv_text, locale="id")
    events = result["events"]
    assert result["row_count"] == 2
    assert result["delimiter"] == ";"
    assert events.iloc[0]["event_type"] == "BUY"
    assert events.iloc[0]["ticker"] == "BBCA"
    assert events.iloc[0]["quantity"] == 1000
    assert events.iloc[0]["price"] == pytest.approx(9250.5)
    assert events.iloc[0]["amount"] == pytest.approx(9250500)
    assert events.iloc[1]["event_type"] == "SELL"


def test_normalizes_english_headers_and_us_number_format():
    csv_text = (
        "Trade Date,Side,Symbol,Qty,Price,Net Amount\n"
        "2026-11-25,BUY,NVDA,2,180.50,361.00\n"
    )
    result = normalize_broker_statement(csv_text, locale="en")
    row = result["events"].iloc[0]
    assert row["date"] == pd.Timestamp("2026-11-25")
    assert row["event_type"] == "BUY"
    assert row["amount"] == pytest.approx(361)
    assert row["price"] == pytest.approx(180.5)


def test_accepts_dataframe_and_keeps_import_read_only():
    source = pd.DataFrame([{
        "tanggal": "25/11/2026", "jenis": "DIVIDEN",
        "nominal": "1.250,50", "kode saham": "BBCA",
    }])
    before = source.copy(deep=True)
    result = normalize_broker_statement(source, locale="id")
    pd.testing.assert_frame_equal(source, before)
    assert result["events"].iloc[0]["event_type"] == "DIVIDEND"
    assert result["events"].iloc[0]["amount"] == pytest.approx(1250.5)


def test_amount_is_absolute_and_warnings_explain_gross_net_ambiguity():
    result = normalize_broker_statement(
        "date,type,amount,ticker\n2026-11-25,DIVIDEND,-1000,BBCA\n"
    )
    assert result["events"].iloc[0]["amount"] == 1000
    assert any("gross atau net" in warning for warning in result["warnings"])


@pytest.mark.parametrize("csv_text, message", [
    ("date,type,amount\n2026-11-25,BUY,100\n", "Kolom wajib"),
    ("date,type,amount,ticker\n2026-11-25,UNKNOWN,100,BBCA\n", "tidak dikenali"),
    ("date,type,amount,ticker\nnot-a-date,BUY,100,BBCA\n", "Tanggal"),
    ("date,type,amount,ticker\n2026-11-25,BUY,not-money,BBCA\n", "Nilai numerik"),
])
def test_rejects_incomplete_or_invalid_statement_rows(csv_text, message):
    with pytest.raises(ValueError, match=message):
        normalize_broker_statement(csv_text)


def test_rejects_ambiguous_duplicate_alias_columns():
    frame = pd.DataFrame([{
        "date": "2026-11-25", "tanggal": "2026-11-25",
        "type": "BUY", "amount": 100, "ticker": "BBCA",
    }])
    with pytest.raises(ValueError, match="ambigu"):
        normalize_broker_statement(frame)


def test_rejects_unsupported_locale():
    with pytest.raises(ValueError, match="locale"):
        normalize_broker_statement("date,type,amount,ticker\n", locale="fr")

def test_auto_locale_treats_three_digit_suffix_as_thousands_separator():
    result = normalize_broker_statement(
        "date;type;amount;ticker;quantity;price\n"
        "2026-11-25;BUY;1,000;BBCA;1,000;1,000\n"
    )
    row = result["events"].iloc[0]
    assert row["amount"] == pytest.approx(1000)
    assert row["quantity"] == pytest.approx(1000)
    assert row["price"] == pytest.approx(1000)


def test_auto_locale_preserves_two_digit_decimal_values():
    result = normalize_broker_statement(
        "date;type;amount;ticker;quantity;price\n"
        "2026-11-25;BUY;1.234,56;BBCA;2;617,28\n",
        locale="id",
    )
    row = result["events"].iloc[0]
    assert row["amount"] == pytest.approx(1234.56)
    assert row["price"] == pytest.approx(617.28)
