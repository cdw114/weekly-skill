# 最小调用示例（**示意**，非正式测试结果）

> 本目录的全部内容都是**示例**，用于说明接口与输出格式。输入是一篇**合成的** 3 页双栏论文（虚构作者、虚构数据），
> 不是比赛用例，也不代表任何真实文献的解析结果。

## 输入
`case.example.json`：
```json
{
  "case_id": "synth-demo-001",
  "pdf": "synth_paper.pdf",
  "output_contract": {"required": ["case_id", "status", "result", "evidence", "uncertainty"]},
  "questions": [
    "What is the table cell accuracy of the proposed method?",
    "How many scanned papers are in DocBench-120?",
    "What is the running time per page?"
  ]
}
```
`synth_paper.pdf`（**不随附**——Skill 资源包只含 UTF-8 文本；运行 `python3 examples/make_synth.py` 生成，需 fpdf2 + 系统 TTF 字体；`src/reproduce.py` 会在首次运行时自动生成）：3 页，含页眉页脚、作者/单位、摘要/关键词、6 个编号章节（含 1.1、4.1 两个二级节）、带合并表头的 Table 1、跨页续表 Table 2、公式 (1)、脚注、5 条参考文献。

## 调用
```bash
mkdir -p work output
python3 scripts/run_case.py --case examples/case.example.json --work work --out output
```
实际输出：
```
[run_case] PDF: …/synth_paper.pdf
[run_case] 3 question(s) to answer: ['What is the table cell accuracy …', 'How many scanned …', 'What is the running time …']
[run_case] done: state=success pages=3/3 unreadable=[] tables=3 blocks=55 -> …/output/result.json
```

## 示意输出
- `result_excerpt.json` — `result.json` 的精简版：`status`、`document` 元数据、`sections` 大纲、前 12 个 `reading_order` id、Table 1 摘要、`equations`、3 个问答（各带 `answer_block` + `evidence`）、`evidence.pages`、`uncertainty`。
- `document_excerpt.md` — `document.md` 的前 48 行：标题、作者、单位、摘要、关键词、大纲（1 / 1.1 / 2 … 6）、正文起始。

问答示例（节选）：
```json
{"question": "What is the running time per page?", "answer": "The runtime of the full pipeline is 1.8 s per page on a single CPU core, compared with 4.1 s for the strongest baseline",
 "status": "found", "confidence": "high", "answer_block": "p2-b03",
 "evidence": [{"id": "p2-b03", "page": 2, "bbox": [312.0, 79.4, 550.0, 168.9], "contains_answer": true}]}
```
`answer_block` 可在 `evidence.block_index` 中找到，对应第 2 页右栏顶部的段落。

## 诚实降级示例（扫描件，无 OCR 引擎）
```json
"status": {"state": "failed", "pages_total": 3, "pages_parsed": 3, "pages_unreadable": [1, 2, 3],
           "notes": ["No OCR engine available (no OCR engine available). Scanned pages will be reported as unreadable.",
                     "page 1: no text layer and OCR unavailable; page reported as unreadable.", …]}
```
安装 `rapidocr_onnxruntime` 后重跑即走 OCR 路径，页标注 `text_source: "ocr:rapidocr"`，低置信行进入 `uncertainty.low_confidence_blocks`。
