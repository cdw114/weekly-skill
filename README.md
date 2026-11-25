# weekly-skill — 阅读01｜文献文档解析

> 把科学 PDF（论文 / 预印本 / 试卷 / 中文报告 / 扫描件）解析为**带页码与坐标定位**的结构化结果。
> 每个输出块都有 `id`、`page`、`bbox`，任何读不出的内容都被显式标记而不是猜测。

Playground「阅读01｜文献文档解析」参赛作品。对应四个评审维度：**提得全**（标题/作者/摘要/章节/表格/公式/图注/脚注/参考文献）、**排得对**（双栏阅读顺序、跨页段落、续表）、**拆得清**（块级结构与类型）、**核得回**（每个结论可回到页码 + 边界框）。

---

## 1. 快速开始

### 环境
- Python ≥ 3.9
- 必需：`PyMuPDF ≥ 1.23`（Harbor 镜像 `pdf-text-tool` 已预装）
- 可选（扫描件 OCR，任一即可）：`rapidocr_onnxruntime`（推荐，纯 onnx 无系统依赖）/ `paddleocr` / `tesseract`（需语言包）/ `ocr-tool` CLI

```bash
pip install -r requirements.txt            # 只装 pymupdf
pip install rapidocr_onnxruntime          # 可选：扫描件 OCR
```

### 从 case.json 运行（平台/比赛用法）
```bash
mkdir -p /app/work /app/output
python3 scripts/run_case.py --case /input/case.json --work /app/work --out /app/output
```
产出：
```
/app/output/
├── result.json          # 契约输出：case_id, status, result, evidence, uncertainty, changes, sources
├── document.json        # 完整结构（含每块 bbox、flags、lines）
├── document.md          # 阅读顺序 Markdown（标题层级、表格、图注、公式、脚注、参考文献）
├── tables/table_p1_1.{md,json,html}   # 每张表：markdown / 带跨度的 grid / html
└── pages/page_001.txt   # 每页按阅读顺序的文本（调试用）
```

### 直接解析一个 PDF（CLI）
```bash
python3 scripts/pdfparse.py paper.pdf out_dir --lang eng --ocr auto --pages 1-20 --questions q.json
```
| 参数 | 说明 |
|-|-|
| `--lang` | OCR 语言（tesseract 代码：`eng`、`chi_sim+eng`…）；runner 默认按文本自动选 |
| `--ocr` | `auto`（依次 rapidocr→paddleocr→tesseract→ocr-tool）/ `off` / 指定引擎 |
| `--pages` | 1-based 页范围，如 `1-3,7` |
| `--dpi` | OCR 渲染分辨率，默认 200 |
| `--questions` | JSON 列表或 `;` 分隔的问题串；结果写入 `document.json.answers` |
| `--lines` | 块内附带逐行细节 |

---

## 2. 输出结构

### result.json（契约）
```jsonc
{
  "case_id": "…",                                   // 来自 case.json
  "status": {"state": "success|partial|failed", "pages_total": 12, "pages_parsed": 12,
             "pages_unreadable": [], "pages_ocr": [3], "uncertain_blocks": 1,
             "elapsed_s": 2.1, "notes": ["OCR fallback ready: rapidocr (rapidocr_onnxruntime)."], "limits": []},
  "result": {
    "document": {"title": "…", "authors": "…", "affiliations": ["…"], "abstract": "…", "keywords": ["…"], "doi": "…", "reference_count": 42},
    "sections": [{"number": "1", "title": "Introduction", "level": 1, "page": 1, "block_id": "p1-b09", "children": [...]}],
    "reading_order": ["p1-b01", "p1-b02", …],      // 全文档阅读顺序
    "tables": [{"id": "p1-b26", "number": "1", "page": 1, "caption": "…", "rows": 6, "cols": 3, "markdown": "| … |"}],
    "figures": [...], "equations": [{"id": "p1-b22", "page": 1, "bbox": [...], "text": "…", "tag": "(1)"}],
    "references": [...], "footnotes": [...],
    "questions": [{"question": "…", "answer": "…", "status": "found", "confidence": "high", "answer_block": "p2-b03",
                   "evidence": [{"id": "p2-b03", "page": 2, "bbox": [...], "contains_answer": true}]}]
  },
  "evidence": {"block_index": [{"id": "p1-b01", "page": 1, "type": "title", "bbox": [...], "text": "…"}],
               "pages": [{"page": 1, "text_source": "text_layer", "columns": 2}],
               "artifacts": {"document_json": "document.json", "document_md": "document.md", "tables_dir": "tables", "pages_dir": "pages"}},
  "uncertainty": {"unreadable_pages": [], "ocr_pages": [], "low_confidence_blocks": [], "notes": [...], "not_done": []},
  "changes": [],                                     // Agent 后续修改记录
  "sources": [{"type": "file", "path": "/input/x.pdf", "sha256": "…", "pages": 12}]
}
```
如果 case.json 给了 `output_contract`，runner 会把相应字段**同时放在顶层**（如 `outline`、`tables`、`answers`、`markdown`）。

### document.json 块类型
`title` `authors` `affiliation` `abstract_label` `abstract` `keywords` `heading` `paragraph` `list` `table` `table_caption` `figure` `caption` `equation` `footnote` `reference` `header` `footer` `page_number` `small_text` `other`
块字段：`id, type, page, bbox, text, level, number, parent, flags, meta, confidence`。跨页续接的段落第二个块带 `meta.continued_from`。

---

## 3. 方法（关键设计）

| 步骤 | 做法 | 解决的问题 |
|-|-|-|
| 行提取 | PyMuPDF span 级 `get_text("dict")`，按基线聚合行；上/下标由字号比 + 垂直偏移恢复为 Unicode；Symbol 字体码点映射 | 公式符号、`⁻`、希腊字母 |
| 原生块 | 利用 PDF 自带 block 编号聚类，减少碎行 | 段落完整性 |
| 栏检测 | 跨栏全宽元素（标题/通栏表/图注）切成**带**；每带内用 2pt 竖条覆盖率找空白列，要求两侧各 ≥25% 行、允许 ≤2 行跨越 | 双栏阅读顺序；跨栏图注不破坏切点 |
| 阅读顺序 | 块按行顺序编号，最终排序只用编号；表格插到其栏内位于其下方第一个文本块前 | 摘要标签略低于首行仍排在前；表格不跳到页首 |
| 页眉页脚 | 归一化文本跨页重复（≥2 页）才判定；纯数字/符号不算；脚注永远不是页眉 | 不同页眉不误删正文；页码不污染表格 |
| 分类 | 字号比 + 粗/斜体 + 正则（章节号 `1.`/`1.1`/`III.`/`A.`/`一、`、`Fig./Table`、`[n]`、`(N)`、列表符）；纯数字大字非标题 | 中英文混排、幻灯片数字 |
| 表格 | `find_tables` 行列跨度 → 显式 `rowspan/colspan` grid；多层表头检测；续表按表头相似 + "continued" 链接 | 合并单元格、跨页续表 |
| OCR | 页面文字 < 30 字符 → 200 dpi 渲染 → rapidocr/paddleocr/tesseract/ocr-tool；行级置信 < 0.80 标 `uncertain` | 扫描件；不猜 |
| 问答 | 词干化 + bigram 加权 TF-IDF 检索块 → 取最相关句 → 标注 `answer_block` | 答案可核 |

详细算法见 [references/method.md](references/method.md)。

---

## 4. 状态与诚实降级

| 情况 | `status.state` | 说明 |
|-|-|-|
| 全部页有文字层 | `success` | |
| 部分页 OCR、部分页不可读 | `partial` | `pages_unreadable` 列出页码，`notes` 说明原因 |
| 全部页不可读（扫描件无 OCR）/ 加密 / 找不到 PDF | `failed` | `reason` 给出人工接管位置 |
| OCR 低置信、公式乱码 | 块 `flags:["uncertain"]` | `uncertainty.low_confidence_blocks` |

**永远不会**：对读不出的页编造文本；对置信度低的答案用确定语气；隐藏失败原因。

---

## 5. 限制
见 [references/limitations.md](references/limitations.md)。要点：不做 LaTeX 化；不读图内文字；不处理竖排/RTL；超大 PDF 请用 `--pages` 分批。

---

## 6. 最小调用示例与本地自测（**示例**，非正式测试结果）
见 [examples/README.md](examples/README.md)：一个 3 页双栏**合成**论文 → 输入 `case.json` → 命令 → `result.json` 片段。

一键复现自测（合成素材，约 3 s）：
```bash
python3 src/reproduce.py        # 写 execution/results/ 与 execution/run.log
```
它用与评测相同的入口 `scripts/run_case.py` 跑三组：合成论文（15 项核对：标题/作者/单位/关键词/章节树/表格/多层表头/续表/公式/参考文献/阅读顺序/3 个问答）、扫描件（无 OCR 时必须诚实 `failed`）、缺失文件（必须 `failed` 且**不回退到别的 PDF**）。结果在 `execution/results/selftest_summary.json`，当前 **18/18**。`characterization.json` 里的数字全部来自这次自测，**不是**隐藏用例的得分。

---

## 7. 文件清单
```
SKILL.md                      Skill 入口（frontmatter + 执行流程 + 检查清单）
README.md                     本文件
requirements.txt              依赖
GITHUB_URL.txt                公开仓库链接
scripts/run_case.py           case.json → /app/output/result.json
scripts/pdfparse.py            解析器（单文件，可独立 CLI）
src/reproduce.py              本地自测（18 项）
characterization.json         自测结果的表征（明确标注为本地合成素材）
references/method.md          算法细节
references/limitations.md      限制与失败处理
examples/README.md            最小示例（标明为示例）
examples/case.example.json    示例输入
examples/synth_paper.pdf      合成论文（examples/make_synth.py 生成，可复现）
examples/synth_paper_scan.pdf 合成扫描件（无文字层）
examples/make_synth.py        素材生成脚本（fpdf2，跨平台字体查找）
examples/result_excerpt.json  示意输出（精简）
examples/document_excerpt.md  示意输出（前 48 行）
execution/run.log             自测日志
execution/results/            自测产物（synth/ scan/ missing/ + selftest_summary.json）
```
