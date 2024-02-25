def read_lines(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        lines = f.readlines()

    lines = list(filter(lambda x: x, [line.strip() for line in lines]))

    return lines


def write_lines(path, lines, encoding="utf-8"):
    with open(path, mode="w", encoding=encoding) as f:
        f.write(lines)
