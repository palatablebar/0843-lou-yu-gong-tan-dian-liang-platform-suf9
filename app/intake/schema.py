from app.errors import DomainIssue
from app.intake.normalize import canonical


def normalize_header(cells):
    return [canonical(cell) for cell in cells]


def validate_header(header, expected):
    normalized = normalize_header(header)
    expected_norm = normalize_header(expected)
    if normalized == expected_norm:
        return normalized
    # 兼容在标准列之外追加的可选业务列（例如房间合同上限）：
    # 标准列按原顺序出现即可，额外列保留给后续整理层识别。
    position = 0
    for column in normalized:
        if position < len(expected_norm) and column == expected_norm[position]:
            position += 1
    if position == len(expected_norm):
        return normalized
    # 列顺序被调整时，只要标准列齐全也接受（按列名取值，不依赖位置）。
    if expected_norm and set(expected_norm).issubset(set(normalized)) and "" not in expected_norm:
        return normalized
    raise DomainIssue("HEADER_MISMATCH")
