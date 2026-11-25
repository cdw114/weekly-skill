# Attention-free parsing of scientific PDFs: a layout-first approach

*Jane Doe a, John Smith b, Wei Zhang a*  
a Department of Computer Science, Example University, Cambridge, UK  
b Institute for Document Intelligence, Shanghai, China  

> status: **success** · pages 3/3

**Abstract** — We present a layout-first pipeline that converts scientific PDFs into structured, page-grounded documents. Instead of relying on a single  text-extraction  pass,  the  pipeline  segments  each  page  into  blocks,  classifies  them,  orders  them  by  a  column-aware reading-order  model,  and  reconstructs  tables  and  equations  as  structured  objects.  On  a  benchmark  of  120  papers,  the  method reaches a word-level F1 of 0.982 and a table cell accuracy of 0.941, outperforming the strongest baseline by 3.4 points.

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

A B S T R A C T We present a layout-first pipeline that converts scientific PDFs into structured, page-grounded documents. Instead of relying on a single  text-extraction  pass,  the  pipeline  segments  each  page  into  blocks,  classifies  them,  orders  them  by  a  column-aware reading-order  model,  and  reconstructs  tables  and  equations  as  structured  objects.  On  a  benchmark  of  120  papers,  the  method reaches a word-level F1 of 0.982 and a table cell accuracy of 0.941, outperforming the strongest baseline by 3.4 points.  `p1-b07` p1


## 1 Introduction  `p1-b08` p1

The  volume  of  scientific  literature  grows  faster  than  any researcher can read. Automated assistants that summarize, translate  or  answer  questions  over  papers  therefore depend  on  a  faithful  conversion  of  the  PDF  into  text  and structure.  Yet  the  Portable  Document  Format  was  never designed  to  carry  semantics:  it  is  a  page-description language  in  which  glyphs  are  placed  at  absolute coordinates, and the logical structure is at best an optional tag.  `p1-b09` p1

Naive extraction that sorts glyphs by their vertical position interleaves  the  two  columns  of  a  double-column  page, producing  sentences  that  read  "the  model  was  trained  on 12,431  pairs  of  images  and  achieves  state-of-the-art results"  out  of  two  unrelated  paragraphs.  Downstream translation and question answering then inherit these errors silently. This paper argues that the ordering problem must be solved at the level of layout blocks rather than individual characters,  and  that  every  extracted  span  should  carry  a pointer back to the page region it came from.  `p1-b10` p1


### 1.1 Contributions  `p1-b11` p1

… (truncated; see examples/README.md)