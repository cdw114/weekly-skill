# 方法：布局优先的 PDF 解析

目标：把 PDF 页面上的 glyph 流还原为**有结构、有顺序、可定位**的文档对象。所有判断只用几何 + 字体 + 文本特征，不依赖训练模型，保证可复现。

坐标约定：PDF 原始坐标（原点左上，单位 pt），`bbox = [x0, y0, x1, y1]`。页宽高取自第 1 页。

---

## 1. 行提取（`extract_lines`）
- `page.get_text("dict")` → block → line → span。每个 span 有 `text, size, font, flags, bbox`。
- 同一行内相邻 span 若字号比 < 0.80 且基线上移 ≥ 15% → 上标；下移 → 下标；映射到 Unicode（`⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾`、`₀-₉` 等），否则保留 `_{}`/`^{}`。
- `font` 含 `Symbol`/`CMMI` 且字符为私用区/非法码点 → 通过码点表映射（α β γ … Σ ∑ ∈ ≠）。
- 字体/字号采用"最长文本 span"的属性作为行属性：`size, bold, italic, font`。
- `Line` 字段：`text, bbox, size, font, bold, italic, page, block_no, meta`；属性 `x0,y0,x1,y1,cx,cy,width`。

## 2. 页面文字层判定与 OCR
- `sum(len(line.text)) < 30` → 视为无文字层。
- OCR 顺序：rapidocr_onnxruntime → rapidocr → paddleocr → tesseract (pytesseract 或 CLI `tsv`) → `ocr-tool` CLI。
- 每个 OCR 行带 `meta.ocr_conf ∈ [0,1]`；`< OCR_LOW_CONF (0.80)` → `meta.uncertain=True`，块的 `flags` 加 `uncertain`。
- CLI 无法给出几何时，按段落均分页面高度，`meta.geometry="unknown"`，整页块标 `uncertain`。

## 3. 正文字号（`body_font_size`）
所有行字号的加权众数（按字符数加权，排除页眉页脚区）。用于计算 `size_ratio = size / body_size`。

## 4. 页眉页脚（`detect_header_footer`）
- 对每页 `cy < 0.12H` 与 `cy > 0.88H` 的行：`normalize_running(text)` = 小写、数字→`#`、去空白。
- 同一归一文本出现在 ≥ 2 页（或 ≥ 50% 页）→ `top_texts / bottom_texts`；`page_number_line`：纯数字/罗马数字/`n / m` 在底部或侧边。
- `running_kind(line)`：
  - `FOOTNOTE_RE` 匹配且字号 < 9.5 → 永不判页眉（`*Corresponding author`、`†`、`1 footnote`）
  - 字母数 < 3 的行（纯数字、符号）→ 不按重复文本判定，只按 `page_number_line`
  - 顶部 10% 且在 `top_texts` → `header`；底部 10% 且在 `bottom_texts` → `footer`；页码 → `page_number`
- `top_limit / bottom_limit` 只取自已分类 running lines 的边界。

## 5. 栏检测与阅读顺序
### 5.1 原生块聚类（`_native_blocks`）
按 `block_no` 把行分组（OCR 行 `block_no=-1` 各自成组），用于 `same_paragraph` 的"同块"判断。

### 5.2 带与栏（`_column_regions`）
输入：去掉 running lines 与表格内行、并暂去掉"脚注样行"（`y0 > 0.80H` 且 `size < 0.92·body`）的行。
1. 按基线把行聚成"行组"（y 重叠 ≥ 50%）。
2. **全宽组**：组内行的 x 覆盖 `[min_x0, max_x1]` 且左右两侧没有别的行（左右 ≥ 0.5 cm 空白）→ 作为带分隔符；单独成带，`cut=None`。
3. 其余相邻行组合成一个带；对每个带调 `_line_column_cut`：
   - 2 pt 竖条覆盖率 `cover[k]`；`cover ≤ 2` 的连续空带为候选 gutter。
   - 候选宽 ≥ 12 pt，且 `x1 ≤ gutter_left` 的行数 ≥ max(2, ⌈0.25·n⌉)，`x0 ≥ gutter_right` 同样 → 取最宽者为 `cut_x`。
   - 不满足 → 单栏 `cut=None`。
4. 返回 `bands = [(y0, y1, lines, cut_x)]`，`ncols = max(2 if any cut else 1, …)`。

### 5.3 带内排序（`_order_band_lines`）
- 有 `cut`：左栏（`cx < cut`）按 `(y0, x0)`，然后右栏。跨越 `cut` 的行（图注、通栏句）归左栏但保持 y 序。
- 无 `cut`：全部 `(y0, x0)`。

### 5.4 后处理
- `_promote_labels`：粗体短标签（ABSTRACT / Keywords: / 摘要）若比其正文首行低 ≤ 6 pt 且同 x 起点 → 提到正文前。
- `_merge_same_baseline`：同基线（dy ≤ 2.5）、x 相邻（≤ 60 pt）、字号接近（< 2）、非"两段都粗" → 合并为一行（`Article history: Received …`）。`merged_fragments` 记在 meta。
- 脚注样行按最后一个双栏带的 `cut` 归到各栏末尾。

### 5.5 分类（`classify_line`，按阅读顺序）
顺序：running → reference（在 refs 区或 `[n]`/`n.` 开头）→ footnote（`FOOTNOTE_RE` 且小字）→ caption（`Fig./Figure/Table/图/表` + 编号）→ heading：
- `SECTION_RE` 命中（`1.`/`1.1`/`III.`/`A.`/`一、第1章`）且 < 120 字，且（粗或 `r ≥ 1.05`），且**非纯数字**
- `r ≥ 1.15` 且 < 90 字，非纯数字
- `r ≥ 1.35` 且在顶部 25%，非纯数字 → `title`
- `r ≤ 0.80`：底部 55% 或含 corresponding/e-mail 或数字/符号开头 → `footnote`；否则 `small_text`
- 列表标记（`- • · – —`、`1.`、`a)`、`(i)`）→ `list`
- `(N)` 公式标签且 `is_equation_like`（数学符号占比、短行）→ `equation`
- 其余 `body`；段首粗体 run-in（`**Limitations.** text`）保留在段落内。

### 5.6 建块
- `body` 行：与前行 `same_paragraph`（行距 ≤ 0.6·行高、左对齐或居中对齐、字号接近、上一行不以句末标点结尾或 x 变化小）且同原生块或同带 → 合并为 `paragraph`。
- `caption`：后续小字行（≤ 0.95 body，间距 < 3）并入。
- `merge_adjacent`：同类块按类型允许的垂直间隙合并（heading gap=0 且并排不合并）。
- 给每个块 `order = k`（构造顺序）。

### 5.7 首页 front matter（`label_front_matter`，仅第 1 页）
- 顶部 30% 内字号最大的块 → `title`。
- 其后按位置：`AFFIL_RE`（University/Institute/大学/研究所…）或 ≤ 25 词含 `*†‡`/小写 → `affiliation`；≤ 20 词、不以句号结尾、含逗号/and/标记 → `authors`；`ABSTRACT_LABEL_RE` → `abstract_label`，之后的正常字号段落 → `abstract`；`KEYWORDS_RE` → `keywords`；遇到章节标题停止。
- `abstract_label` 与紧随的 `abstract` 合并，`order` 取较小者。

### 5.8 最终顺序（`_final_order`）
top running blocks → 各带：按 `order` 排序的文本块（双栏：左后右）→ 表格插到其所在栏中位于其下方第一个文本块之前 → bottom running blocks。

## 6. 表格（`extract_tables`）
- `page.find_tables()`；每个表 `t.rows[i].cells` 给出每格 bbox，相同 bbox 合并 → `colspan/rowspan`。
- 与任一 running line 面积重叠 > 30% 的行剔除（`rows_dropped_margin`）。
- `detect_header_rows(grid)`：从首行起，若该行所有非空格在下方行中作为子串出现，或字号/粗体与下方不同，或首行全空 → 计为表头；最多 3 行。
- `table_to_markdown`：多级表头展平为 `H1 / H2`；合并单元格用 `colspan` 重复填充并标注。
- `attach_table_captions`：表上方最近的 `Table N.` caption 关联 `caption_block`；`table_continuations`：下一页首表若表头行相似（Jaccard ≥ 0.5）或 caption 含 `continued` → `continued_from`。

## 7. 图与图注（`find_figure_region`）
`caption` 块附近（上方/下方 200 pt、同栏）的最大图像矩形或绘图聚类 bbox → `figure_region`，输出 `figures[]` 带 `bbox` 与 `placeholder`。

## 8. 文档级
- `stitch_cross_page`：第 N 页最后一段（不以句末结尾）与第 N+1 页首段（小写/逗号开头、同宽）合并，第二块 `meta.continued_from`。
- `build_section_tree`：按标题层级（`1.` level 1，`1.1` level 2，…）建树；`p{page}-b{nn}` id。
- `extract_doc_metadata`：title / authors / affiliations / abstract / keywords（`Keywords:`/`Index Terms`/`关键词`）/ doi / reference_count。

## 9. 问答（`answer_questions`）
- 语料 = 所有非页眉页脚块 + 表格 markdown；token 化：小写、去停用词、轻量词干（`-ing/-ed/-s/-ies`）、复合词拆分（`runtime→run time`）；CJK 按字。
- 打分：TF-IDF（块内 tf，文档 df）+ **bigram 短语命中 ×2**。
- 句级选择：top-3 块内按句切分，`命中词占比 + 0.3·bigram + 数字问题含数字句 +0.15 − 长度惩罚` → `answer`；记录 `answer_block`。
- `confidence`：top1/top3 比值 > 1.5 或仅 1 命中 → high；否则 medium；best_score < 2 → low（`status=uncertain`）；无命中 → `not_found`。

## 10. 复杂度
每页 O(L log L)（L 行数），100 页 < 30 s（不含 OCR）。OCR 时间取决于引擎，rapidocr 约 2–5 s/页。
