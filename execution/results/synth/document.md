# Attention-free parsing of scientific PDFs: a layout-first approach

*Jane Doe a, John Smith b, Wei Zhang a*  
a Department of Computer Science, Example University, Cambridge, UK  
b Institute for Document Intelligence, Shanghai, China  

> status: **success** · pages 3/3

**Abstract** — We present a layout-first pipeline that converts scientific PDFs into structured, page-grounded documents. Instead of relying on a single text-extraction pass, the pipeline segments each page into blocks, classifies them, orders them by a column-aware reading-order model, and reconstructs tables and equations as structured objects. On a benchmark of 120 papers, the method reaches a word-level F1 of 0.982 and a table cell accuracy of 0.941, outperforming the strongest baseline by 3.4 points.

**Keywords** — document parsing; reading order; layout analysis; tables; OCR

## Outline

- `p1-b02` Attention-free parsing of scientific PDFs: a layout-first approach · p1
  - `p1-b08` **1** Introduction · p1
    - `p1-b11` **1.1** Contributions · p1
  - `p1-b16` **2** Related work · p1
  - `p1-b19` **3** Method · p1
  - `p2-b02` **4** Experiments · p2
    - `p2-b04` **4.1** Ablation · p2
  - `p2-b09` **5** Discussion · p2
  - `p2-b12` **6** Conclusion · p2

## Content (reading order)


# Attention-free parsing of scientific PDFs: a layout-first approach  `p1-b02` p1

Jane Doe a, John Smith b, Wei Zhang a  `p1-b03` p1

a Department of Computer Science, Example University, Cambridge, UK b Institute for Document Intelligence, Shanghai, China  `p1-b04` p1

A R T I C L E   I N F O  `p1-b05` p1

Article history: Received 3 March 2026; Received in revised form 21 May 2026; Accepted 2 June 2026 Keywords: document parsing; reading order; layout analysis; tables; OCR  `p1-b06` p1

A B S T R A C T We present a layout-first pipeline that converts scientific PDFs into structured, page-grounded documents. Instead of relying on a single text-extraction pass, the pipeline segments each page into blocks, classifies them, orders them by a column-aware reading-order model, and reconstructs tables and equations as structured objects. On a benchmark of 120 papers, the method reaches a word-level F1 of 0.982 and a table cell accuracy of 0.941, outperforming the strongest baseline by 3.4 points.  `p1-b07` p1


## 1 Introduction  `p1-b08` p1

The volume of scientific literature grows faster than any researcher can read. Automated assistants that summarize, translate or answer questions over papers therefore depend on a faithful conversion of the PDF into text and structure. Yet the Portable Document Format was never designed to carry semantics: it is a page-description language in which glyphs are placed at absolute coordinates, and the logical structure is at best an optional tag.  `p1-b09` p1

Naive extraction that sorts glyphs by their vertical position interleaves the two columns of a double-column page, producing sentences that read "the model was trained on 12,431 pairs of images and achieves state-of-the-art results" out of two unrelated paragraphs. Downstream translation and question answering then inherit these errors silently. This paper argues that the ordering problem must be solved at the level of layout blocks rather than individual characters, and that every extracted span should carry a pointer back to the page region it came from.  `p1-b10` p1


### 1.1 Contributions  `p1-b11` p1

(i) A column-aware reading-order algorithm that handles  `p1-b12` p1

cross-column floats and cross-page paragraphs. (ii) A table reconstructor that resolves merged cells and multi-level headers into a rectangular grid with explicit spans. (iii) A grounding layer that attaches page and bounding box to every output element, and marks unreadable regions instead of guessing.1  `p1-b13` p1

Figure 1. Overview of the pipeline. Pages are segmented into blocks, blocks are classified, then ordered.  `p1-b14` p1

[ figure placeholder : pipeline diagram ]  `p1-b15` p1


## 2 Related work  `p1-b16` p1

Early systems such as pdftotext exposed the content stream in drawing order, which is correct only for single-column documents produced by well-behaved tools. Poppler and MuPDF later added layout modes that detect columns from the horizontal projection of text lines. Machine-learning approaches, notably LayoutLM and its successors, treat layout analysis as a detection problem and learn block classes from annotated corpora. Commercial systems integrate OCR for scanned inputs but typically hide the confidence of each recognized span.  `p1-b17` p1

Our work differs in two respects. First, we treat reading order as a function of block geometry only, without a learned model, which keeps the pipeline reproducible across versions. Second, we make uncertainty explicit: regions that cannot be read are reported with their location and a reason rather than filled with a guess.  `p1-b18` p1


## 3 Method  `p1-b19` p1

Let a page be a set of blocks B = {b1, ..., bn} with bounding boxes in page coordinates. We first assign each block to a column region using a recursive XY-cut, then order blocks within each region top-to-bottom and regions left-to-right. The reading-order score is  `p1-b20` p1

R = Σ_i  w_i · log p(b_i | b_<i)      (1)  `p1-b21` p1

where w_i is a salience weight and p is a position prior. For tables, we extract the ruling lines, intersect them to form cells, and merge cells whose shared border is missing. Greek letters and subscripts are recovered from font metadata: the temperature parameter θ and the learning rate η{sub}t{/sub} are emitted as Unicode; the activation is  `p1-b22` p1

σ(x) = 1 / (1 + e{sup}−x{/sup}), with α = 0.01 and ΔG = −12.4 kJ mol{sup}−1{/sup}.  `p1-b23` p1

Table 1. Comparison with baselines on the DocBench-120 test set.  `p1-b24` p1


| Method | Accuracy (%) |  |
|---|---|---|
|  | Text F1 | Table cell |
| pdftotext -layout | 0.871 | 0.612 |
| Poppler layout | 0.893 | 0.704 |
| LayoutLM-base | 0.948 | 0.907 |
| Ours | 0.982 | 0.941 |

*Table 0 — p1, bbox [308.98, 693.92, 552.76, 790.3] (`p1-b25`)*

Best results in bold. All numbers are averages over three seeds.  `p1-b26` p1


## 4 Experiments  `p2-b02` p2

We evaluate on DocBench-120, a collection of 120 papers from six publishers, of which 18 are scanned images without a text layer. Each paper was annotated by two students with block boundaries, reading order and table structure; disagreements were resolved by a third annotator. Table 2 reports the per-document-type breakdown. The runtime of the full pipeline is 1.8 s per page on a single CPU core, compared with 4.1 s for the strongest baseline, a 2.3× speed-up.  `p2-b03` p2


### 4.1 Ablation  `p2-b04` p2

Removing the column detection lowers text F1 from 0.982 to 0.791, confirming that ordering errors dominate the error budget. Removing the table merge step lowers cell accuracy from 0.941 to 0.863. Both components are therefore necessary; neither alone suffices.  `p2-b05` p2

Table 2. Results by document type (continues on the next page).  `p2-b06` p2


| Document type | Count | Text F1 |
|---|---|---|
| Born-digital, 1 column | 31 | 0.991 |
| Born-digital, 2 columns | 48 | 0.985 |
| Born-digital, ≥3 columns | 23 | 0.962 |

*Table 1 — p2, bbox [42.52, 291.4, 286.3, 355.18] (`p2-b07`)*

Table 2 (continued)  `p2-b08` p2


## 5 Discussion  `p2-b09` p2

The remaining errors concentrate in three areas: equations set with custom math fonts whose ToUnicode map is missing, tables whose ruling lines are drawn as very light gray and fall below the threshold, and running headers that change between pages. We consider the first the most important: a missing ToUnicode map makes an equation unreadable regardless of the layout model, and the only honest output is to report the region as unreadable with its bounding box.  `p2-b10` p2

Limitations. Our evaluation covers English only. Scripts without spaces and vertical writing need a different line-segmentation stage. The pipeline also does not currently interpret chart data; figures are reported as blocks with their captions and a placeholder, which is sufficient for question answering about the caption but not about the plotted values.  `p2-b11` p2


## 6 Conclusion  `p2-b12` p2

A layout-first pipeline with explicit grounding turns a PDF into a structure that downstream agents can cite. We release the code and the annotation guidelines.  `p2-b13` p2

1 A preliminary version of this work appeared in the workshop proceedings of DocEng 2025.  `p2-b14` p2

* Corresponding author: j.doe@example.edu  `p2-b15` p2

Table 2 (continued)  `p3-b02` p3


| Document type | Count | Text F1 |
|---|---|---|
| Scanned, OCR A | 10 | 0.938 |
| Scanned, OCR B | 8 | 0.911 |

*Table 2 — p3, bbox [42.52, 79.37, 286.3, 127.56] (`p3-b03`)*

Scanned documents were processed with the OCR fallback.  `p3-b04` p3

References  `p3-b05` p3

[1] J. Doe, K. Lee, Block-level reading order for multi-column documents, in: Proceedings of ICDAR, 2024, pp. 112–120.  `p3-b06` p3

[2] Y. Xu, M. Brown, S. Petrov, LayoutLM: Pre-training of text and layout for document image understanding, in: KDD, 2020, pp. 1192–1200.  `p3-b07` p3

[3] A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. Gomez, Ł. Kaiser, I. Polosukhin, Attention is all you need, in: NeurIPS, 2017.  `p3-b08` p3

[4] A. Krizhevsky, I. Sutskever, G. Hinton, ImageNet classification with deep convolutional neural networks, Commun. ACM 60 (6) (2017) 84–90.  `p3-b09` p3

[5] A. Cojocaru, E. B. Smith, D. R. Jones, On the reproducibility of PDF extraction benchmarks, J. Reprod. Sci. 11 (2025) 45–61.  `p3-b10` p3
