"""Offline source date-folder audit and bounded-PDF format rejection."""
import unittest
from v294_szse_time_semantics_pdf_parity import time_audit, inspect_pdf


def synthetic():
    rows=[]
    for i in range(486):
        day="2023-08-31"
        folder="2023-08-30" if i<174 else day
        rows.append({"ann_id":str(1217706310+i),"publication_day":day,
                     "exchange_publish_time_raw":day+" 00:00:00",
                     "exchange_relative_path":"/disc/disk03/finalpage/"+folder+
                     "/6f55fe41-cade-4647-ab62-24622baab47f.PDF",
                     "exchange_stock_codes":["002667"],
                     "title":"威领股份：Synthetic official announcement"})
    return rows


class TimeSemanticsTests(unittest.TestCase):
    def test_date_folder_mismatch_does_not_certify_historical_time(self):
        out=time_audit(synthetic())
        self.assertTrue(out["all_source_rows_structurally_valid"])
        self.assertEqual(out["exchange_midnight_display_count"],486)
        self.assertEqual(out["date_folder_delta_days"],{"0":312,"1":174})
        self.assertFalse(out["exact_publication_timestamp_proven"])
        self.assertFalse(out["cninfo_original_locator_temporal_semantics_proven"])

    def test_no_auto_admission_for_bad_issuer_or_broken_identity(self):
        x=synthetic()
        x[0]["exchange_stock_codes"]=["009999"]
        self.assertFalse(time_audit(x)["all_source_rows_structurally_valid"])
        with self.assertRaisesRegex(ValueError,"EXACT_SOURCE_486_ROWS_REQUIRED"):
            time_audit(x[:485])

    def test_pdf_check_needs_real_pdf_bytes(self):
        with self.assertRaisesRegex(ValueError,"NOT_BOUNDED_ORIGINAL_PDF"):
            inspect_pdf(b"not-a-pdf")


if __name__=="__main__":
    unittest.main()
