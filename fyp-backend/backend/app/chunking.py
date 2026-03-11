import re
from typing import List, Tuple

def split_numbered_answers(text: str) -> List[Tuple[int, str]]:
    """
    Splits answers when it finds question headers like:
      1. ...
      1) ...
      1 - ...
      1: ...
      Q1. ...
      Q 2) ...
      Question 3: ...
    Returns list of (question_no, chunk_text)

    Fallback:
    - if numbering is not detected, return the whole text as Q1
    """
    text = (text or "").strip()
    if not text:
        return []

    pattern = re.compile(
        r"""(?mix)
        ^\s*
        (?:question\s*)?
        (?:q\s*)?
        (\d{1,3})
        \s*
        (?:[\.\)\:\-–—])
        \s+
        """,
    )

    matches = list(pattern.finditer(text))
    if not matches:
        return [(1, text)]

    chunks: List[Tuple[int, str]] = []
    for i, m in enumerate(matches):
        qno = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append((qno, chunk))

    if not chunks:
        return [(1, text)]

    return chunks


def clean_text_basic(s: str) -> str:
    # remove common PDF artifacts
    s = re.sub(r"\(cid:\d+\)", "", s)
    s = s.replace("\u00ad", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
