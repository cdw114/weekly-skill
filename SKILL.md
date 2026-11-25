---
name: weekly-skill
description: 阅读01｜文献文档解析 — 把科学 PDF（论文/试题/中文报告，含扫描件）解析为带页码与坐标定位的结构化结果。当任务给出 PDF 并要求提取标题/作者/摘要/章节/表格/公式/参考文献、回答基于文档的问题、或生成可追溯的阅读结果时使用。产出 /app/output/result.json（含 case_id、status、result、evidence、uncertainty）。
---

# 文献文档解析 Skill（weekly-skill）

一个**布局优先、可追溯**的科学 PDF 解析流程。单文件解析器 `scripts/pdfparse.py`（PyMuPDF）+ 案例入口 `scripts/run_case.py`。
输出块提供 `id`（`p{页}-b{序号}`）、`page`、`bbox` 和 `flags`。坐标未知时，`bbox` 为 `null`。读不出或有疑义的内容保留原因与页码。

## 何时使用
- 输入是 PDF（论文、预印本、试卷、技术报告、中文文档），需要：全文结构化、章节大纲、表格（含合并单元格/多层表头/跨页续表）、公式、图注、脚注、参考文献。
- 需要基于文档回答问题并给出可复核的证据位置。
- 扫描件（无文字层）→ 自动 OCR 回退；没有 OCR 引擎时如实报告 `unreadable`。

## 执行流程（严格按顺序，不要跳步）

### 第 0 步：读输入，不要假设内容
```bash
cat /input/case.json          # 可能有 case_id、pdf 路径、questions、output_contract
cat /input/task.md 2>/dev/null || true
ls -la /input /app/input /data 2>/dev/null   # 找到实际 PDF 文件
```
**必须读实际 PDF**。核对任务指定的是论文、试题还是补充材料。用 `--pdf` 明确选择来源。记录原始 `case_id`，从 `case.json` 和 `task.md` 抄出每个必填字段、字段类型、所需文件名及任务范围。

### 第 1 步：检查依赖（30 秒内完成，失败直接进入降级）
```bash
python3 -c "import fitz; print('PyMuPDF', fitz.__doc__)"   # 必需；镜像已预装 pdf-text-tool
python3 -c "import rapidocr_onnxruntime" 2>/dev/null || python3 -c "import rapidocr" 2>/dev/null || echo "no rapidocr"
which tesseract ocr-tool 2>/dev/null; tesseract --list-langs 2>/dev/null | head -5
```
- 没有 PyMuPDF 时尝试 `python3 -m pip install -r /skills/weekly-skill/requirements.txt`，然后运行入口。若仍缺依赖，入口会写带原始 `case_id` 的失败结果。
- OCR 引擎全部缺失：**不是失败**，解析仍可进行；扫描页会被标为 `unreadable`，并在 `status.notes` 中说明。可选安装 `rapidocr_onnxruntime`（纯 onnx，无系统依赖）。

### 第 2 步：运行解析（一条命令，不要手工拆解）
```bash
mkdir -p /app/work /app/output
cd /skills/weekly-skill/scripts
python3 run_case.py --case /input/case.json --work /app/work --out /app/output
```
用 `--max-seconds` 给解析、OCR 和版面整理留出预算，默认 800 秒。若必须优先处理任务指定页，可传 `--pages 1-20`。未处理页会列在 `uncertainty.not_done` 中。

可选参数：`--pdf 路径`（case.json 没写 pdf 时）、`--lang chi_sim+eng|eng`（OCR 语言，默认自动检测中英）、`--ocr auto|off|tesseract|rapidocr|paddleocr|ocr-tool`、`--dpi 200`、`--password`、`--questions q.json`。

### 第 3 步：检查结果，然后才算完成
```bash
python3 - <<'EOF'
import json; r=json.load(open('/app/output/result.json',encoding='utf-8'))
s=r['status']; print('state', s['state'], '| pages', s['pages_parsed'],'/',s['pages_total'], '| unreadable', s['pages_unreadable'], '| ocr', s['pages_ocr'], '| uncertain', s['uncertain_blocks'])
for n in s['notes'][:8]: print(' note:', n)
print('title:', r['result']['document'].get('title')); print('sections:', len(r['result']['sections']), 'tables:', len(r['result']['tables']), 'eqs:', len(r['result']['equations']), 'refs:', len(r['result']['references']))
for q in r['result'].get('questions', []): print(' Q', q['status'], q['confidence'], q['answer_block'], '|', q['answer'][:100] if q['answer'] else None)
EOF
head -60 /app/output/document.md
```
必须核对的 5 件事（发现问题就修参数重跑，最多 3 次）：
1. **state 正确吗？** `failed`/`partial` 时，`uncertainty.unreadable_pages` 和 `notes` 是否给出了可人工接管的原因？
2. **阅读顺序对吗？** 双栏论文若在 `document.md` 里出现左右栏句子交错（一句话里突然跳到另一段），说明栏检测失败 → 看该页 `pages/page_NNN.txt`；可用 `--dpi` 或检查页面是否有跨栏大图。
3. **表格完整吗？** 每个 `tables/table_*.md` 的表头行数与原文是否一致，续表是否被标记 `continued_from`。
4. **问题答案是否有证据？** 对每个候选打开原 PDF 的对应页，检查原句、表的行和列、单位、实验条件和例外。能确认时把 `status` 更新为 `verified`，将 `requires_verification` 改为 `false`，保留正确的 `answer_block` 和页码、坐标。重新定位时同步更新 `evidence`。证据不足则标 `uncertain` 或 `not_found` 并写明查过的位置。
5. **文件齐全吗？** 解析有产物时，确认 `result.json` 内引用的文件均可打开。有结构表格时检查 `tables/` 中对应的 JSON、Markdown 和 HTML。加密、缺文件或缺依赖时，以 `result.json` 的失败状态和原因为准。

### 第 4 步：按任务要求补充（如果 case 要求特定输出）
- 入口只自动填充能从解析结果映射的字段。`uncertainty.contract_errors` 列出待补齐或类型有误的项。用实际 PDF 和任务要求填入正确的字段与文件。遇到缺失来源时按契约报告缺失，保留 `partial`，避免填造内容。明确要求文件路径的字段使用输出目录内的文件，要求内联 Markdown 的字段填 Markdown 正文。
- 更新 `result.json.changes[]`，记录 `what`、`why`、`source_blocks` 和适用的 `file`。同步更新问答别名字段。清理已解决的契约错误和待复核项。只有所有任务输出通过核验且无未处理页时，才把 `status.state` 更新为 `success`。
- 任何 Agent 生成的结论，引用块 id（如 `p3-b12`），不要引用行号或臆造页码。
- 生成 Office/图片/图表类交付物时，同时输出真实渲染的 PDF/PNG 预览。
- 交付前运行下面的命令。它检查必填项、基本类型、嵌套字段、文件和问答锚点。按原始契约再检查任务语义及校验器未覆盖的高级约束。

  ```bash
  python3 /skills/weekly-skill/scripts/run_case.py --case /input/case.json --out /app/output --validate-result
  ```

## 输出契约（result.json）
| 字段 | 内容 |
|-|-|
| `case_id` | 来自 case.json；缺失时用 case 文件名，并在 `status.notes` 说明 |
| `status` | `state`: success / partial / failed；`pages_parsed/total`、`pages_unreadable`、`pages_ocr`、`uncertain_blocks`、`elapsed_s`、`notes[]`（每条异常原因）、`limits[]` |
| `result.document` | title / authors / affiliations / abstract / keywords / doi / reference_count |
| `result.sections` | 嵌套大纲 `{number,title,level,page,block_id,children[]}` |
| `result.reading_order` | 全文档块的阅读顺序 id 列表 |
| `result.tables[]` | id、number、caption、page、rows/cols、markdown（含合并单元格），完整 grid/cells 在 `tables/table_*.json` |
| `result.figures[]` / `equations[]` / `references[]` / `footnotes[]` | 带 page、bbox 的列表 |
| `result.questions[]` | 每问含 answer、status、confidence、answer_block、evidence[] 和 requires_verification。脚本生成待复核候选 |
| `evidence.block_index[]` | 每个块的 id/page/bbox/type/前 160 字 —— 可直接回到页面坐标复核 |
| `uncertainty` | unreadable_pages、ocr_pages、low_confidence_blocks、notes、not_done[] |
| `changes[]` | Agent 对解析结果所做的后续修改记录 |
| `sources[]` | 输入文件路径、sha256、页数 |

## 关键方法（为什么这样做）
1. **行级提取 → 原生块 → 全宽分组 → 分带 XY 切分栏**：先按 PyMuPDF 原生块聚类，再把跨栏的全宽元素（标题、通栏表格、图注）作为“带分隔符”，在每个带内用垂直空白带找栏切点（要求两侧各 ≥25% 的行、允许 ≤2 行跨越），左栏自上而下再右栏。脚注/通讯作者行按栏归位，不参与切栏估计。
2. **页眉页脚只认跨页重复文本**：对每页顶/底部行做归一化（数字→#），≥2 页重复才判为 running head；纯数字/单符号不算；带 `*`/`†`/email 的脚注永远不是页眉。页面 zone 边界只由已分类的 running lines 决定，不会被大标题抬高。
3. **分类靠字号比 + 粗斜体 + 正则**：章节号 `1.`/`1.1`/`III.`/`A.`、`Fig./Table` 图表注、`[12]`/`12.` 参考文献、`(N)` 公式标签、列表标记；纯数字大字（幻灯片统计数字）不当标题；同一基线的“标签 + 值”（Article history: …）合并为一行。
4. **阅读顺序 = 构造顺序**：块按行阅读顺序编号，最终排序只用该编号；表格插到其所在栏中位于其下方第一个文本块之前。这避免了 bbox 排序把“标签略低于首行”的摘要标签排到后面。
5. **表格**：`find_tables` 行列跨度 → 显式 `rowspan/colspan` 的 grid；多层表头检测；跨页续表通过表头行相似 + "continued" 关键词链接 `continued_from`；与 running head 重叠的行剔除。
6. **公式与符号**：上/下标由 span 字号比 + 垂直偏移恢复为 Unicode；Symbol 字体缺 ToUnicode 时用码点映射。
7. **OCR 回退**：页面文字少于 30 字符时渲染页面。自动模式在引擎报错、超时、无文字或低置信时尝试下一可用引擎。保留来源和失败原因。坐标未知时标记 `bbox: null`，全失败或无文字的页计入 `unreadable`。

## 失败与降级处理（必须如实）
| 情况 | 行为 | status |
|-|-|-|
| 找不到 PDF | 写 result.json，`state=failed`，reason 写明查找过的路径 | failed |
| PDF 加密且无密码 | `failed`，reason "encrypted PDF" | failed |
| 扫描件、无 OCR 引擎 | 页面 `no_text_layer`，计入 `pages_unreadable`，`notes` 写明可安装 rapidocr | failed（全部页）/ partial |
| OCR 置信度低 | 块 `flags:["uncertain"]`，`uncertainty.low_confidence_blocks` 列出 | partial |
| 限时停止或指定部分页 | `uncertainty.not_done` 列出未处理页 | partial |
| 栏检测失败 | 单栏顺序输出；`pages[].layout.columns=1` | success（但在 notes 提示） |
| 表格识别失败 | 该区域按文本块输出，不生成表格 | success |
| 公式乱码（缺 ToUnicode） | 文本照实输出并标 `uncertain`，不猜测 | partial |

## 限制（写进 result 的 `status.limits`）
- 不做公式 LaTeX 化（输出 Unicode 文本 + 坐标）；不读图内文字（需 OCR 图像）；不处理竖排/阿拉伯语 RTL 排版。
- 中文文档：章节号正则支持“一、/第1章/1.1”，但中文粗体检测依赖字体名，若字体内嵌不全可能漏判。
- 页数 > 100 的 PDF 请用 `--pages` 分批。

## 自查清单（提交前）
- [ ] `python3 run_case.py` 在仅安装解析依赖的环境能产出 result.json
- [ ] 用扫描件验证 OCR 成功和失败后的逐页回退。关闭 OCR 时验证不可读页的状态
- [ ] 双栏论文 document.md 无栏交错
- [ ] 每个问答 answer_block 能在 evidence.block_index 找到
- [ ] result.json 通过 `--validate-result`，且按 task.md 核对实际交付物

## 文件
- `scripts/run_case.py` — 入口（case.json → result.json）
- `scripts/pdfparse.py` — 解析器（可独立 CLI：`python3 pdfparse.py in.pdf out_dir [--lang --ocr --pages --questions]`）
- `scripts/output_contract.py` — 字段映射、输出契约和证据定位检查
- `requirements.txt`、`README.md`（完整方法/接口/示例）、`references/method.md`（算法细节）、`references/limitations.md`
- `examples/` — 最小示例（输入、命令、**示意**输出）；`examples/make_synth.py` 生成合成测试 PDF（需 fpdf2）
- `src/reproduce.py` — 本地自测 18 项（`python3 src/reproduce.py`），产物在 `execution/`
