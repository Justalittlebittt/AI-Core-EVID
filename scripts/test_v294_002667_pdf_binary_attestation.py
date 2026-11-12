"""Source-binary attestations must fail closed on missing fields or non-PDF bytes."""
import unittest
import fitz
from v294_002667_pdf_binary_attestation import check_pdf


class BinaryAttestationTests(unittest.TestCase):
    def test_non_pdf_blocked(self):
        with self.assertRaisesRegex(ValueError,"NOT_A_BOUNDED_PDF"):
            check_pdf(b"not-a-pdf","synthetic")

    def test_pdf_with_no_matching_issuer_not_admitted(self):
        doc=fitz.open()
        page=doc.new_page()
        page.insert_text((30,30),"A harmless synthetic document")
        a=check_pdf(doc.tobytes(),"synthetic")
        self.assertEqual(a["pages"],1)
        self.assertFalse(a["field_checks_pass"])
        self.assertFalse(any(a["content_fields"].values()))


if __name__=="__main__":
    unittest.main()
