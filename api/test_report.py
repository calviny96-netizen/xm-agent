"""Inspect exported PDFs, including pagination, text preservation and link placement."""
from io import BytesIO
import unittest
from urllib.parse import unquote

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from report import build_report, BODY_FONT_SIZE, BODY_BOTTOM, BODY_TOP, fit_paragraph
from reportlab.lib.pagesizes import A4


def listing(text, phone='081234567890', score=85):
    return {'raw_text': text, 'normalized_text': text, 'contact_phone': phone, 'score': score}


@unittest.skipUnless(PdfReader, 'install api/requirements-test.txt to inspect PDF output')
class ReportPDFTests(unittest.TestCase):
    def read(self, pairs, direction='buyer'):
        return PdfReader(BytesIO(build_report(pairs, direction)))

    def test_exactly_one_a4_portrait_page_per_selected_pair(self):
        long_text = '\n'.join(f'Baris {i:03d}: rumah Surabaya Barat, luas 120 m2, harga Rp 2 M.' for i in range(100))
        pdf = self.read([(listing('Buyer singkat'), listing('Listing singkat')),
                         (listing(long_text + '\nAKHIR SUMBER'), listing(long_text + '\nAKHIR TARGET')),
                         (listing('Buyer tanpa pasangan'), None)])
        self.assertEqual(len(pdf.pages), 3)
        for page in pdf.pages:
            self.assertAlmostEqual(float(page.mediabox.width), A4[0], places=3)
            self.assertAlmostEqual(float(page.mediabox.height), A4[1], places=3)
        self.assertIn('AKHIR SUMBER', pdf.pages[1].extract_text())
        self.assertIn('AKHIR TARGET', pdf.pages[1].extract_text())
        self.assertIn('Baris 099', pdf.pages[1].extract_text())
        self.assertIn('Belum ada kecocokan.', pdf.pages[2].extract_text())

    def test_body_defaults_to_11pt_and_shrinks_only_the_long_column(self):
        long_text = '\n'.join(f'LONG {i}: Semua informasi listing harus tetap tercetak.' for i in range(90))
        page = self.read([(listing('SHORT body stays eleven'), listing(long_text))]).pages[0]
        sizes = {'short': set(), 'long': set()}

        def inspect(text, cm, tm, font, size):
            if 'SHORT' in text: sizes['short'].add(size)
            if 'LONG' in text: sizes['long'].add(size)

        page.extract_text(visitor_text=inspect)
        self.assertEqual(sizes['short'], {11})
        self.assertTrue(sizes['long'])
        self.assertTrue(all(0 < size < 11 for size in sizes['long']))

    def test_only_right_hand_contact_is_linked_in_both_directions(self):
        for direction in ['buyer', 'property']:
            with self.subTest(direction=direction):
                page = self.read([(listing('SUMBER', '081111111111'), listing('TARGET', '082222222222'))], direction).pages[0]
                links = [a.get_object() for a in page.get('/Annots', [])]
                self.assertEqual(len(links), 1)
                self.assertGreater(float(links[0]['/Rect'][0]), A4[0] / 2)
                self.assertIn('wa.me/628222222222', links[0]['/A']['/URI'])
                message = unquote(links[0]['/A']['/URI'])
                self.assertIn('listing properti' if direction == 'buyer' else 'kebutuhan properti', message)
                self.assertEqual(page.extract_text().count('WhatsApp:'), 1)
                self.assertNotIn('628111111111', page.extract_text())

    def test_no_green_contact_for_missing_target_phone_or_unmatched_source(self):
        for target in [None, listing('No phone', '')]:
            page = self.read([(listing('Source has phone'), target)]).pages[0]
            self.assertEqual(len(page.get('/Annots', [])), 0)
            self.assertNotIn('WhatsApp:', page.extract_text())


class ReportLayoutTests(unittest.TestCase):
    def test_long_text_fits_above_actions_without_truncation_or_overflow(self):
        for text in ['Short listing', '\n'.join(['Long listing content.'] * 180), 'X' * 12000]:
            paragraph, height = fit_paragraph(text)
            self.assertLessEqual(height, BODY_TOP - BODY_BOTTOM)
            self.assertLessEqual(paragraph.style.fontSize, BODY_FONT_SIZE)
            self.assertGreater(paragraph.style.fontSize, 0)
            # ReportLab records each line's remaining width; negative would overflow.
            self.assertGreaterEqual(min(line.extraSpace for line in paragraph.blPara.lines) if paragraph.blPara.kind == 1 else
                                    min(line[0] for line in paragraph.blPara.lines), -0.01)


if __name__ == '__main__':
    unittest.main()
