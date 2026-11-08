import unittest
from unittest.mock import patch

import pandas as pd

from idx_fundamentals import fetch_idx_fundamentals, get_fundamentals_summary


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.income_stmt = pd.DataFrame(
            [[1000, 900]],
            index=['Total Revenue'],
            columns=[pd.Timestamp('2025-12-31'), pd.Timestamp('2024-12-31')],
        )
        self.balance_sheet = pd.DataFrame(
            [[500, 450]],
            index=['Total Assets'],
            columns=[pd.Timestamp('2025-12-31'), pd.Timestamp('2024-12-31')],
        )
        self.cashflow = pd.DataFrame(
            [[100, 80]],
            index=['Free Cash Flow'],
            columns=[pd.Timestamp('2025-12-31'), pd.Timestamp('2024-12-31')],
        )

    def get_info(self):
        return {
            'longName': 'Example Indonesia Tbk',
            'sector': 'Basic Materials',
            'industry': 'Industrial Materials',
            'financialCurrency': 'IDR',
        }


class IdxFundamentalsTests(unittest.TestCase):

    @patch('idx_fundamentals.yf.Ticker', FakeTicker)
    def test_idx_symbol_is_resolved_and_company_metadata_loaded(self):
        data = fetch_idx_fundamentals('BBCA')
        self.assertEqual(data['ticker'], 'BBCA.JK')
        self.assertEqual(data['currency'], 'IDR')
        self.assertEqual(data['company_name'], 'Example Indonesia Tbk')
        self.assertEqual(data['reported_currency'], 'IDR')

    @patch('idx_fundamentals.yf.Ticker', FakeTicker)
    def test_all_three_historical_statements_are_loaded(self):
        data = fetch_idx_fundamentals('BBCA')
        self.assertEqual(set(data['statements']), {'income_statement', 'balance_sheet', 'cash_flow'})
        self.assertEqual(data['statements']['income_statement'].loc['Total Revenue'].iloc[0], 1000)
        self.assertEqual(data['statements']['cash_flow'].loc['Free Cash Flow'].iloc[1], 80)

    @patch('idx_fundamentals.yf.Ticker', FakeTicker)
    def test_historical_periods_are_preserved(self):
        data = fetch_idx_fundamentals('BBCA')
        self.assertEqual(data['periods']['income_statement'], ['2025-12-31', '2024-12-31'])
        self.assertEqual(data['periods']['balance_sheet'], ['2025-12-31', '2024-12-31'])

    @patch('idx_fundamentals.yf.Ticker', FakeTicker)
    def test_summary_reports_statement_coverage(self):
        summary = get_fundamentals_summary(fetch_idx_fundamentals('BBCA'))
        income = summary['statements']['income_statement']
        self.assertEqual(income['rows'], 1)
        self.assertEqual(income['period_count'], 2)
        self.assertEqual(income['non_null_cells'], 2)
        self.assertEqual(income['missing_cells'], 0)

    @patch('idx_fundamentals.yf.Ticker', FakeTicker)
    def test_missing_cells_generate_warning_and_are_counted(self):
        with patch.object(FakeTicker, '__init__', autospec=True) as init:
            def setup(instance, symbol):
                instance.symbol = symbol
                instance.income_stmt = pd.DataFrame(
                    [[1000, None]], index=['Total Revenue'],
                    columns=[pd.Timestamp('2025-12-31'), pd.Timestamp('2024-12-31')]
                )
                instance.balance_sheet = pd.DataFrame(
                    [[500, 450]], index=['Total Assets'],
                    columns=[pd.Timestamp('2025-12-31'), pd.Timestamp('2024-12-31')]
                )
                instance.cashflow = pd.DataFrame(
                    [[100, 80]], index=['Free Cash Flow'],
                    columns=[pd.Timestamp('2025-12-31'), pd.Timestamp('2024-12-31')]
                )
            init.side_effect = setup
            with patch.object(FakeTicker, 'get_info', return_value={'financialCurrency': 'IDR'}):
                data = fetch_idx_fundamentals('BBCA')
        summary = get_fundamentals_summary(data)
        self.assertEqual(summary['statements']['income_statement']['missing_cells'], 1)
        self.assertTrue(any('tidak lengkap' in warning for warning in data['warnings']))

    @patch('idx_fundamentals.yf.Ticker', FakeTicker)
    def test_non_idx_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            fetch_idx_fundamentals('AAPL.US')


if __name__ == '__main__':
    unittest.main()
