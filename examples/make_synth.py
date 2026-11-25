"""Synthesize a realistic two-column scientific paper PDF for testing the parser (example fixture only).

Produces (next to this script):
   synth_paper.pdf        - born-digital, 2-column, 3 pages, with header/footer, abstract, keywords,
                            numbered sections, figure+table captions, a multi-level-header table with
                            rowspan/colspan, footnotes, an equation with Greek/superscripts, references.
   synth_paper_scan.pdf   - same pages rendered to grayscale JPEG and re-embedded (no text layer).

Requires: fpdf2, pymupdf and a TTF sans-serif font (Arial / Liberation Sans / DejaVu Sans).
Run: python3 make_synth.py
"""
import glob
import os
import sys

try:
    from fpdf import FPDF
except ImportError:
    sys.exit("pip install fpdf2 pymupdf")
import pymupdf

OUT = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)


def find_font(*families):
    """Return (regular, bold, italic) TTF paths, searching common system font directories."""
    win = os.environ.get("WINDIR", r"C:\Windows") + "\\Fonts" if os.name == "nt" else "/usr/share/fonts/truetype"
    dirs = [win, "/usr/share/fonts", "/Library/Fonts", "/System/Library/Fonts/Supplemental", os.path.expanduser("~/.fonts")]
    for reg, bold, ital in families:
        found = []
        for name in (reg, bold, ital):
            hit = None
            for d in dirs:
                if os.path.isdir(d):
                    hits = glob.glob(os.path.join(d, "**", name), recursive=True)
                    if hits:
                        hit = hits[0]; break
            found.append(hit)
        if all(found):
            return found
    sys.exit("No sans-serif TTF found (looked for Arial / LiberationSans / DejaVuSans)")


F_REG, F_BOLD, F_ITAL = find_font(("arial.ttf", "arialbd.ttf", "ariali.ttf"),
                                  ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf"),
                                  ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf"))
pdf = FPDF(format='A4', unit='mm')
pdf.set_auto_page_break(False)
pdf.add_font('DejaVu', '', F_REG)
pdf.add_font('DejaVu', 'B', F_BOLD)
pdf.add_font('DejaVu', 'I', F_ITAL)

W, H = 210, 297
L, R = 15, 15          # margins
TOP, BOT = 22, 20
COL_W = 86
GAP = 8
COL1_X = L
COL2_X = L + COL_W + GAP

def header_footer(page_no, title, journal):
    pdf.set_font('DejaVu', 'I', 7.5)
    pdf.set_y(10)
    pdf.set_x(L); pdf.cell(120, 4, journal, align='L')
    pdf.set_x(R + 0); pdf.set_x(W - R - 60); pdf.cell(60, 4, title, align='R')
    pdf.set_font('DejaVu', '', 8)
    pdf.set_y(H - 12)
    pdf.set_x(L); pdf.cell(30, 4, 'Preprint submitted to ' + journal, align='L')
    pdf.set_x(W/2 - 10); pdf.cell(20, 4, str(page_no), align='C')
    pdf.set_x(W - R - 40); pdf.cell(40, 4, 'Doe et al.', align='R')

def para(text, size=9, lh=4.2, style='', align='J'):
    pdf.set_font('DejaVu', style, size)
    pdf.multi_cell(0, lh, text, align=align)

def run_in_column(x, w, fn):
    pdf.set_x(x)
    # emulate column by using a temporary x/margin trick: fpdf multi_cell uses l-margin; we set it
    ml = pdf.l_margin
    pdf.set_left_margin(x)
    pdf.set_right_margin(W - (x + w))
    fn()
    pdf.set_left_margin(ml)
    pdf.set_right_margin(R)

# ---------------- PAGE 1 ----------------
pdf.add_page()
header_footer(1, 'Attention-free parsing of scientific PDFs', 'Journal of Reproducible Science 12 (2026) 1–14')

pdf.set_y(16)
def centered(text, style, size, lh):
    pdf.set_font('DejaVu', style, size)
    pdf.set_x(L)
    pdf.multi_cell(W - 2*L, lh, text, align='C')
centered('Attention-free parsing of scientific PDFs: a layout-first approach', 'B', 13, 7)
centered('Jane Doe a, John Smith b, Wei Zhang a', '', 10, 6)
centered('a Department of Computer Science, Example University, Cambridge, UK', 'I', 8.5, 5)
centered('b Institute for Document Intelligence, Shanghai, China', 'I', 8.5, 5)

pdf.set_y(40)
pdf.set_font('DejaVu', 'B', 9)
pdf.set_x(L); pdf.cell(0, 5, 'A R T I C L E   I N F O', align='L', new_x='LMARGIN', new_y='NEXT')
pdf.set_font('DejaVu', '', 8)
y = pdf.get_y()
pdf.set_xy(L, y); pdf.cell(30, 4, 'Article history:', align='L', new_x='RIGHT', new_y='TOP')
pdf.cell(0, 4, 'Received 3 March 2026; Received in revised form 21 May 2026; Accepted 2 June 2026', align='L', new_x='LMARGIN', new_y='NEXT')
y = pdf.get_y()
pdf.set_xy(L, y); pdf.cell(30, 4, 'Keywords:', align='L', new_x='RIGHT', new_y='TOP')
pdf.cell(0, 4, 'document parsing; reading order; layout analysis; tables; OCR', align='L', new_x='LMARGIN', new_y='NEXT')

pdf.set_y(56)
pdf.set_font('DejaVu', 'B', 9)
pdf.set_x(L); pdf.cell(0, 5, 'A B S T R A C T', align='L')
pdf.set_font('DejaVu', '', 8.5)
abs_text = ('We present a layout-first pipeline that converts scientific PDFs into structured, page-grounded '
            'documents. Instead of relying on a single text-extraction pass, the pipeline segments each page into '
            'blocks, classifies them, orders them by a column-aware reading-order model, and reconstructs tables '
            'and equations as structured objects. On a benchmark of 120 papers, the method reaches a word-level '
            'F1 of 0.982 and a table cell accuracy of 0.941, outperforming the strongest baseline by 3.4 points.')
pdf.set_x(L); pdf.multi_cell(W - 2*L, 4.2, abs_text, align='J')

# two columns start
pdf.set_y(88)
y_top = pdf.get_y()

# Column 1
def col1_p1():
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '1. Introduction', align='L')
    pdf.ln(6)
    para('The volume of scientific literature grows faster than any researcher can read. Automated assistants that '
         'summarize, translate or answer questions over papers therefore depend on a faithful conversion of the PDF '
         'into text and structure. Yet the Portable Document Format was never designed to carry semantics: it is a '
         'page-description language in which glyphs are placed at absolute coordinates, and the logical structure '
         'is at best an optional tag.')
    pdf.ln(2)
    para('Naive extraction that sorts glyphs by their vertical position interleaves the two columns of a '
         'double-column page, producing sentences that read "the model was trained on 12,431 pairs of images and '
         'achieves state-of-the-art results" out of two unrelated paragraphs. Downstream translation and question '
         'answering then inherit these errors silently. This paper argues that the ordering problem must be solved '
         'at the level of layout blocks rather than individual characters, and that every extracted span should '
         'carry a pointer back to the page region it came from.')
    pdf.ln(2)
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '1.1. Contributions', align='L')
    pdf.ln(6)
    para('(i) A column-aware reading-order algorithm that handles cross-column floats and cross-page paragraphs. '
         '(ii) A table reconstructor that resolves merged cells and multi-level headers into a rectangular grid '
         'with explicit spans. (iii) A grounding layer that attaches page and bounding box to every output element, '
         'and marks unreadable regions instead of guessing.1')
    pdf.ln(2)
    # Figure 1 in column
    pdf.set_font('DejaVu', 'B', 8.5)
    pdf.cell(16, 5, 'Figure 1.', align='L', new_x='RIGHT', new_y='TOP')
    pdf.set_font('DejaVu', '', 8.5)
    pdf.cell(0, 5, 'Overview of the pipeline. Pages are segmented into blocks, blocks are classified, then ordered.', align='L')
    pdf.ln(4)
    pdf.rect(COL1_X + 10, pdf.get_y(), COL_W - 20, 40)
    pdf.set_font('DejaVu', 'I', 7)
    pdf.set_xy(COL1_X + 12, pdf.get_y() + 16)
    pdf.cell(0, 4, '[ figure placeholder : pipeline diagram ]', align='L')
    pdf.ln(44)

# Column 2
def col2_p1():
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '2. Related work', align='L')
    pdf.ln(6)
    para('Early systems such as pdftotext exposed the content stream in drawing order, which is correct only for '
         'single-column documents produced by well-behaved tools. Poppler and MuPDF later added layout modes that '
         'detect columns from the horizontal projection of text lines. Machine-learning approaches, notably '
         'LayoutLM and its successors, treat layout analysis as a detection problem and learn block classes from '
         'annotated corpora. Commercial systems integrate OCR for scanned inputs but typically hide the confidence '
         'of each recognized span.')
    pdf.ln(2)
    para('Our work differs in two respects. First, we treat reading order as a function of block geometry only, '
         'without a learned model, which keeps the pipeline reproducible across versions. Second, we make '
         'uncertainty explicit: regions that cannot be read are reported with their location and a reason rather '
         'than filled with a guess.')
    pdf.ln(2)
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '3. Method', align='L')
    pdf.ln(6)
    para('Let a page be a set of blocks B = {b1, ..., bn} with bounding boxes in page coordinates. We first '
         'assign each block to a column region using a recursive XY-cut, then order blocks within each region '
         'top-to-bottom and regions left-to-right. The reading-order score is')
    pdf.ln(3)
    pdf.set_font('DejaVu', '', 9.5)
    pdf.set_x(COL2_X + 20)
    pdf.cell(0, 6, 'R = Σ_i  w_i · log p(b_i | b_<i)      (1)', align='L')
    pdf.ln(8)
    pdf.set_font('DejaVu', '', 9)
    para('where w_i is a salience weight and p is a position prior. For tables, we extract the ruling lines, '
         'intersect them to form cells, and merge cells whose shared border is missing. Greek letters and '
         'subscripts are recovered from font metadata: the temperature parameter θ and the learning rate η'
         '{sub}t{/sub} are emitted as Unicode; the activation is σ(x) = 1 / (1 + '
         'e{sup}−x{/sup}), with α = 0.01 and ΔG = −12.4 kJ mol{sup}−1{/sup}.', style='')
    pdf.ln(2)
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(15, 5, 'Table 1.', align='L', new_x='RIGHT', new_y='TOP')
    pdf.set_font('DejaVu', '', 8.5)
    pdf.cell(0, 5, 'Comparison with baselines on the DocBench-120 test set.', align='L')
    pdf.ln(6)
    draw_table1()

def draw_table1():
    # multi-level header with a spanning top row
    x0 = COL2_X
    y0 = pdf.get_y()
    widths = [34, 26, 26]
    pdf.set_font('DejaVu', '', 8)
    # row 1: spanning header
    pdf.set_xy(x0, y0); pdf.cell(widths[0], 6, 'Method', border=1, align='C')
    pdf.set_xy(x0 + widths[0], y0); pdf.cell(widths[1] + widths[2], 6, 'Accuracy (%)', border=1, align='C')
    # row 2: sub headers
    y1 = y0 + 6
    pdf.set_xy(x0, y1); pdf.cell(widths[0], 6, '', border=1)
    pdf.set_xy(x0 + widths[0], y1); pdf.cell(widths[1], 6, 'Text F1', border=1, align='C')
    pdf.set_xy(x0 + widths[0] + widths[1], y1); pdf.cell(widths[2], 6, 'Table cell', border=1, align='C')
    rows = [('pdftotext -layout', '0.871', '0.612'),
            ('Poppler layout', '0.893', '0.704'),
            ('LayoutLM-base', '0.948', '0.907'),
            ('Ours', '0.982', '0.941')]
    y = y1 + 6
    for r in rows:
        pdf.set_xy(x0, y); pdf.cell(widths[0], 5.5, r[0], border=1)
        pdf.set_xy(x0 + widths[0], y); pdf.cell(widths[1], 5.5, r[1], border=1, align='C')
        pdf.set_xy(x0 + widths[0] + widths[1], y); pdf.cell(widths[2], 5.5, r[2], border=1, align='C')
        y += 5.5
    pdf.set_xy(x0, y + 1)
    pdf.set_font('DejaVu', 'I', 7)
    pdf.set_x(x0); pdf.multi_cell(COL_W, 3.2, 'Best results in bold. All numbers are averages over three seeds.', align='L')
    pdf.set_y(y + 8)

# We need to run the columns at same top: capture y positions by drawing sequentially in each column.
# fpdf can't do real columns; emulate: record y_top, draw col1 from y_top, then reset y to y_top and draw col2.
y0 = 88
pdf.set_xy(COL1_X, y0); run_in_column(COL1_X, COL_W, col1_p1)
y_end1 = pdf.get_y()
pdf.set_xy(COL2_X, y0); run_in_column(COL2_X, COL_W, col2_p1)
y_end2 = pdf.get_y()

# ---------------- PAGE 2 ----------------
pdf.add_page()
header_footer(2, 'Attention-free parsing of scientific PDFs', 'Journal of Reproducible Science 12 (2026) 1–14')

def col1_p2():
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '4. Experiments', align='L'); pdf.ln(6)
    para('We evaluate on DocBench-120, a collection of 120 papers from six publishers, of which 18 are scanned '
         'images without a text layer. Each paper was annotated by two students with block boundaries, reading '
         'order and table structure; disagreements were resolved by a third annotator. Table 2 reports the '
         'per-document-type breakdown. The runtime of the full pipeline is 1.8 s per page on a single CPU core, '
         'compared with 4.1 s for the strongest baseline, a 2.3× speed-up.')
    pdf.ln(2)
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '4.1. Ablation', align='L'); pdf.ln(6)
    para('Removing the column detection lowers text F1 from 0.982 to 0.791, confirming that ordering errors '
         'dominate the error budget. Removing the table merge step lowers cell accuracy from 0.941 to 0.863. '
         'Both components are therefore necessary; neither alone suffices.')
    pdf.ln(2)
    # Table 2 with a rowspan-style "Continued on next page" to test cross-page continuation
    pdf.set_font('DejaVu', 'B', 8.5)
    pdf.cell(16, 5, 'Table 2.', align='L', new_x='RIGHT', new_y='TOP')
    pdf.set_font('DejaVu', '', 8.5)
    pdf.cell(0, 5, 'Results by document type (continues on the next page).', align='L')
    pdf.ln(6)
    x0 = COL1_X; y = pdf.get_y()
    w = [40, 23, 23]
    pdf.set_font('DejaVu', '', 8)
    pdf.set_xy(x0, y); pdf.cell(w[0], 6, 'Document type', border=1, align='C')
    pdf.set_xy(x0 + w[0], y); pdf.cell(w[1], 6, 'Count', border=1, align='C')
    pdf.set_xy(x0 + w[0] + w[1], y); pdf.cell(w[2], 6, 'Text F1', border=1, align='C')
    y += 6
    for r in [('Born-digital, 1 column', '31', '0.991'), ('Born-digital, 2 columns', '48', '0.985'),
              ('Born-digital, ≥3 columns', '23', '0.962')]:
        pdf.set_xy(x0, y); pdf.cell(w[0], 5.5, r[0], border=1)
        pdf.set_xy(x0 + w[0], y); pdf.cell(w[1], 5.5, r[1], border=1, align='C')
        pdf.set_xy(x0 + w[0] + w[1], y); pdf.cell(w[2], 5.5, r[2], border=1, align='C')
        y += 5.5
    pdf.set_y(y + 1)
    pdf.set_font('DejaVu', 'I', 7)
    pdf.set_x(x0); pdf.cell(0, 3.5, 'Table 2 (continued)', align='L')
    pdf.set_y(y + 5)

def col2_p2():
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '5. Discussion', align='L'); pdf.ln(6)
    para('The remaining errors concentrate in three areas: equations set with custom math fonts whose ToUnicode '
         'map is missing, tables whose ruling lines are drawn as very light gray and fall below the threshold, '
         'and running headers that change between pages. We consider the first the most important: a missing '
         'ToUnicode map makes an equation unreadable regardless of the layout model, and the only honest output '
         'is to report the region as unreadable with its bounding box.')
    pdf.ln(2)
    para('Limitations. Our evaluation covers English only. Scripts without spaces and vertical writing need a '
         'different line-segmentation stage. The pipeline also does not currently interpret chart data; figures '
         'are reported as blocks with their captions and a placeholder, which is sufficient for question '
         'answering about the caption but not about the plotted values.')
    pdf.ln(2)
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 5, '6. Conclusion', align='L'); pdf.ln(6)
    para('A layout-first pipeline with explicit grounding turns a PDF into a structure that downstream agents '
         'can cite. We release the code and the annotation guidelines.')
    pdf.ln(2)
    # Footnote marker text (footnote at bottom of column)
    pdf.set_font('DejaVu', '', 7)
    pdf.set_y(H - BOT - 24)
    pdf.set_x(COL2_X)
    pdf.multi_cell(COL_W, 3.2, '1 A preliminary version of this work appeared in the workshop proceedings of DocEng 2025.', align='L')
    pdf.set_y(H - BOT - 10)
    pdf.set_font('DejaVu', '', 7)
    pdf.set_x(COL2_X)
    pdf.multi_cell(COL_W, 3.2, '* Corresponding author: j.doe@example.edu', align='L')

y0 = 22
pdf.set_xy(COL1_X, y0); run_in_column(COL1_X, COL_W, col1_p2)
pdf.set_xy(COL2_X, y0); run_in_column(COL2_X, COL_W, col2_p2)

# ---------------- PAGE 3 : references + continued table ----------------
pdf.add_page()
header_footer(3, 'Attention-free parsing of scientific PDFs', 'Journal of Reproducible Science 12 (2026) 1–14')

pdf.set_y(22)
pdf.set_font('DejaVu', 'B', 10)
pdf.set_x(L); pdf.cell(0, 5, 'Table 2 (continued)', align='L'); pdf.ln(6)
x0 = L; y = pdf.get_y(); w = [40, 23, 23]
pdf.set_font('DejaVu', '', 8)
pdf.set_xy(x0, y); pdf.cell(w[0], 6, 'Document type', border=1, align='C')
pdf.set_xy(x0 + w[0], y); pdf.cell(w[1], 6, 'Count', border=1, align='C')
pdf.set_xy(x0 + w[0] + w[1], y); pdf.cell(w[2], 6, 'Text F1', border=1, align='C')
y += 6
for r in [('Scanned, OCR A', '10', '0.938'), ('Scanned, OCR B', '8', '0.911')]:
    pdf.set_xy(x0, y); pdf.cell(w[0], 5.5, r[0], border=1)
    pdf.set_xy(x0 + w[0], y); pdf.cell(w[1], 5.5, r[1], border=1, align='C')
    pdf.set_xy(x0 + w[0] + w[1], y); pdf.cell(w[2], 5.5, r[2], border=1, align='C')
    y += 5.5
pdf.set_xy(x0, y + 1)
pdf.set_font('DejaVu', 'I', 7); pdf.set_x(x0); pdf.cell(0, 3.5, 'Scanned documents were processed with the OCR fallback.', align='L')

pdf.set_y(y + 14)
pdf.set_font('DejaVu', 'B', 10)
pdf.set_x(L); pdf.cell(0, 5, 'References', align='L'); pdf.ln(6)
refs = [
 '[1] J. Doe, K. Lee, Block-level reading order for multi-column documents, in: Proceedings of ICDAR, 2024, pp. 112–120.',
 '[2] Y. Xu, M. Brown, S. Petrov, LayoutLM: Pre-training of text and layout for document image understanding, in: KDD, 2020, pp. 1192–1200.',
 '[3] A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. Gomez, Ł. Kaiser, I. Polosukhin, Attention is all you need, in: NeurIPS, 2017.',
 '[4] A. Krizhevsky, I. Sutskever, G. Hinton, ImageNet classification with deep convolutional neural networks, Commun. ACM 60 (6) (2017) 84–90.',
 '[5] A. Cojocaru, E. B. Smith, D. R. Jones, On the reproducibility of PDF extraction benchmarks, J. Reprod. Sci. 11 (2025) 45–61.',
]
for r in refs:
    pdf.set_font('DejaVu', '', 8)
    pdf.set_x(L); pdf.multi_cell(W - 2*L, 3.8, r, align='L')
    pdf.ln(0.8)

pdf.output(os.path.join(OUT, 'synth_paper.pdf'))
print('wrote synth_paper.pdf')

# scanned version: render pages to PNG, re-embed into a new PDF
src = pymupdf.open(os.path.join(OUT, 'synth_paper.pdf'))
dst = pymupdf.open()
for page in src:
    pix = page.get_pixmap(dpi=110, colorspace=pymupdf.csGRAY)
    newp = dst.new_page(width=page.rect.width, height=page.rect.height)
    newp.insert_image(newp.rect, stream=pix.tobytes("jpeg", jpg_quality=55))
dst.save(os.path.join(OUT, 'synth_paper_scan.pdf'), garbage=3, deflate=True)
print('wrote synth_paper_scan.pdf')
