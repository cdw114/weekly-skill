# 限制与失败处理

## 会被如实标记、不会被猜测的情况

| 情况 | 检测方式 | 输出 | 接管建议 |
|-|-|-|-|
| 扫描件且无 OCR 引擎 | 页面文字 < 30 字符、无可用引擎 | `status.state=failed`，`pages_unreadable=[…]`，`notes` 列出尝试过的引擎 | `pip install rapidocr_onnxruntime` 后重跑；或把扫描页交给独立 OCR 流程 |
| OCR 页置信度低 | 行 `ocr_conf < 0.80` | 块 `flags:["uncertain"]`，`uncertainty.low_confidence_blocks` | 对照 `pages/page_NNN.txt` 与渲染图人工校对 |
| OCR 引擎崩溃 | 异常 | 该页 `text_source=ocr_failed`，`notes` 含异常类型 | 换引擎 `--ocr tesseract` 或提高 `--dpi` |
| PDF 加密 | `doc.needs_pass` 且空密码失败 | `failed`，reason `encrypted PDF` | 用 `--password` |
| 公式缺 ToUnicode | 字体 Symbol/CMMI + 私用区码点 | 文本照实输出 + `uncertain` | 对照页面图像人工转写 |
| 表格无线条 | `find_tables` 失败 | 按文本块输出，不生成表格 | 记录在 `status.notes` |

## 已知局限（写入 `status.limits`）
1. **不做 LaTeX 化**：公式输出为 Unicode 文本 + 页面坐标，`H_2O` 可读但不是 `$H_2O$`。
2. **不读图内文字**：图中的曲线标签、流程框文字不提取（需要图像 OCR，目前只对无文字层页面做 OCR）。
3. **竖排 / RTL**：中文竖排、阿拉伯语/希伯来语不处理，会按行从上到下错误排序。
4. **多栏 > 2 栏**：XY 切分只保证 1–2 栏正确；3 栏报纸版面会被当成 2 栏或单栏。
5. **中文粗体检测**依赖字体名含 `Bold/黑体/Heavy`，字体内嵌不全时漏判，只靠字号比。
6. **章节号正则**覆盖 `1.`/`1.1`/`III.`/`A.`/`一、`/`第1章`/`（一）`，自定义编号（`§1.2-a`）需加正则。
7. **跨页表格**：只在下一页**首个**表且表头相似时链接；表头在续表页变化时断开。
8. **大 PDF**：> 100 页请用 `--pages` 分批；单次 OCR > 600 s 时先出部分结果（`partial`）。
9. **问答**是词法检索（TF-IDF + bigram + 句选择），不做推理；`not_found`/`uncertain` 不改写成确定答案。
10. **Front matter 启发式**：标题/作者/单位按位置与关键词判定，作者行含单位名时会被分成 `affiliation`；不影响全文内容完整性。

## 失败处理原则
1. **先保产物**：任何异常都要写出 `result.json`（哪怕 `state=failed`），让平台拿到可诊断信息。
2. **原因可定位**：每条 `notes` 含页码或异常类型。
3. **不补造**：读不出的页不生成文本；低置信答案保留 `uncertain`。
4. **增量**：超时前先完成部分页并标 `partial`，`uncertainty.not_done` 列出未完成页。
