---
name: weekly-skill
description: 阅读01｜解析科学 PDF，按 case.json 和 task.md 交付带页码与证据位置的文本、结构、表格或问答。支持双栏和扫描页 OCR 回退。
---

# 阅读01｜文献文档解析

## 1. 读题并解析

读取 `/input/case.json` 和 `/input/task.md`，确定必交字段、文件和范围，然后运行：

```bash
python3 /skills/weekly-skill/scripts/run_case.py
```

脚本会选正文、检测依赖、按需 OCR，并输出 `/app/output/result.json` 和简短待办。提示多份 PDF 有歧义时，只检查题目和材料列表，再加 `--pdf 实际路径` 重跑。依赖缺失时按报错处理。

## 2. 按待办核对原文

按题目核对所需字段、文件和关键页。用命令输出的页码和块 ID 定位原 PDF。需要更多上下文时再看 `/app/output/pages/page_NNN.txt` 或 `tables/` 下的对应表格。全文和算法说明按需打开。

- 问答候选需要核对原 PDF 的原句、表头、行、单位和实验条件。确认后在 `result.json` 的 `result.questions` 填写 `answer`、`answer_block`，并把该条的 `status` 改为 `verified`。块 ID 可在 `evidence.block_index` 中查到。坐标是去除页面旋转后的 PDF 点坐标。
- 补齐 `output_contract` 的必交字段和文件。自行修订的内容用 `changes` 记录修改、理由和来源块。无法确认的内容保留不确定标记并说明原因，需编辑的交付物及预览按题目提供。

## 3. 收尾并校验

```bash
python3 /skills/weekly-skill/scripts/run_case.py --finalize
```

脚本更新已确认答案的证据和自动投影的答案字段，检查输出约定、页数和引用文件。按报错修订后再运行。`valid: true` 表示通过校验，`state` 依然区分完整、部分和失败。`--validate-result` 可以只校验现有结果。

开发说明见 `README.md`，原理见 `references/method.md`，适用边界见 `references/limitations.md`，合成测试见 `examples/`。
