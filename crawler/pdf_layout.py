"""Preserve observable PDF table cells without inferring names or row ownership."""
import io
from collections import Counter


def _characters(text):
    return Counter(char for char in text if not char.isspace())


def complete_pages(raw, pages):
    """Use drawn cell boundaries only; ordinary text pages retain the existing text."""
    import pdfplumber

    result = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if len(pdf.pages) != len(pages):
            raise ValueError('PDF页码数量不一致，不能自动核验')
        for page, original in zip(pdf.pages, pages):
            tables = page.find_tables()
            if not tables:
                result.append(dict(original))
                continue
            cells = [cell for table in tables for cell in table.cells]
            # Mixed narrative/table layouts need a dedicated reading-order parser.
            # Never drop text outside a detected table or count overlapping cells twice.
            for char in page.chars:
                if not char['text'].strip():
                    continue
                x, y = (char['x0'] + char['x1']) / 2, (char['top'] + char['bottom']) / 2
                if sum(left <= x <= right and top <= y <= bottom for left, top, right, bottom in cells) != 1:
                    raise ValueError('PDF表格外或重叠单元格含正文，尚不能完整确定版面顺序')
            plain, lines, locators = [], [], []
            for index, table in enumerate(tables, 1):
                xs = sorted({x for cell in table.cells for x in (cell[0], cell[2])})
                ys = sorted({y for cell in table.cells for y in (cell[1], cell[3])})
                lines.append(f"PDF第{original['page']}页 表{index}（行列跨度取自绘制边框；单元格内换行保留）")
                seen = set()
                for row, values in zip(table.rows, table.extract()):
                    for cell, text in zip(row.cells, values):
                        if cell is None or cell in seen:
                            continue
                        seen.add(cell)
                        top, bottom = ys.index(cell[1]) + 1, ys.index(cell[3])
                        left, right = xs.index(cell[0]) + 1, xs.index(cell[2])
                        row_label = str(top) if top == bottom else f'{top}-{bottom}'
                        col_label = str(left) if left == right else f'{left}-{right}'
                        text = text or ''
                        plain.append(text)
                        lines.append(f'行{row_label} 列{col_label}：{text}')
                        locators.append(dict(table=index, rows=[top, bottom], columns=[left, right],
                                             bbox=list(cell), text=text))
                if seen != set(table.cells):
                    raise ValueError('PDF表格单元格未完整提取，不能自动核验')
            if _characters(''.join(plain)) != _characters(original['text']):
                raise ValueError('PDF表格文字覆盖与原始文本层不一致，不能自动核验')
            result.append(dict(original, text='\n'.join(lines), extraction='drawn_cells_v1',
                               text_coverage='all_nonwhitespace_characters', cells=locators))
    return result
