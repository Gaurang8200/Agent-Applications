"""Measure how many rendered lines each CV bullet occupies in the final PDF.

Character counts are only a proxy for line length — the ground truth is the
rendered document. This module extracts the text lines from the generated PDF
and maps each bullet back onto the lines it spans, so the pipeline can verify
the 1.75–2.0-line rule against reality and feed precise corrections back to
the tailor stage.
"""

import re
from dataclasses import dataclass

from pypdf import PdfReader

_BULLET_PREFIX = re.compile(r"^[•◦▪‣\-•\s]+")
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


@dataclass
class BulletRender:
    text: str
    lines: int | None  # None = could not be located in the PDF text
    first_line_chars: int = 0
    last_line_chars: int = 0

    def ratio(self) -> float | None:
        """Approximate rendered length in lines, e.g. 1.6 for a short 2nd line."""
        if self.lines is None:
            return None
        if self.lines <= 1:
            return 1.0
        full = max(self.first_line_chars, 1)
        return (self.lines - 1) + min(self.last_line_chars / full, 1.0)


def pdf_text_lines(pdf_path: str) -> list[str]:
    reader = PdfReader(pdf_path)
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(line for line in text.splitlines())
    return lines


def measure_bullets(pdf_path: str, bullets: list[str]) -> list[BulletRender]:
    raw_lines = pdf_text_lines(pdf_path)
    norm_lines = [_norm(_BULLET_PREFIX.sub("", line)) for line in raw_lines]

    results: list[BulletRender] = []
    for bullet in bullets:
        target = _norm(bullet)
        found: BulletRender | None = None
        for start in range(len(norm_lines)):
            if not norm_lines[start] or not target.startswith(norm_lines[start][:20]):
                continue
            acc = ""
            spans: list[str] = []
            for j in range(start, min(start + 6, len(norm_lines))):
                candidate = norm_lines[j]
                acc = _norm(f"{acc} {candidate}") if acc else candidate
                spans.append(candidate)
                if acc == target:
                    found = BulletRender(
                        text=bullet,
                        lines=len(spans),
                        first_line_chars=len(spans[0]),
                        last_line_chars=len(spans[-1]),
                    )
                    break
                if not target.startswith(acc):
                    break
            if found:
                break
        results.append(found or BulletRender(text=bullet, lines=None))
    return results


def line_violations(
    measured: list[BulletRender], min_ratio: float = 1.75, max_lines: int = 2
) -> list[str]:
    """Human-readable problems, suitable to feed back to the tailor stage."""
    problems: list[str] = []
    for index, m in enumerate(measured):
        r = m.ratio()
        if m.lines is None:
            continue  # unverifiable — don't block on extraction quirks
        if m.lines > max_lines:
            problems.append(
                f"bullet {index + 1} renders as {m.lines} lines (max {max_lines}); "
                f"shorten it: {m.text[:60]}..."
            )
        elif r is not None and r < min_ratio:
            problems.append(
                f"bullet {index + 1} renders as only {r:.2f} lines (min {min_ratio}); "
                f"lengthen it: {m.text[:60]}..."
            )
    return problems
