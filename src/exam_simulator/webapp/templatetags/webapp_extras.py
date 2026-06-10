from __future__ import annotations

import html
import re

from django import template
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter
def get_item(value: dict, key: str):
    if not isinstance(value, dict):
        return None
    return value.get(key)


_FENCED_CODE_RE = re.compile(r"```([A-Za-z0-9_-]+)?\s*\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


@register.filter
def rich_question(value: object):
    text = "" if value is None else str(value)
    chunks = []
    cursor = 0
    for match in _FENCED_CODE_RE.finditer(text):
        chunks.append(_format_plain_question_text(text[cursor:match.start()]))
        language = (match.group(1) or "text").strip().lower()
        code = match.group(2).strip("\n")
        chunks.append(
            '<pre class="question-code-block" data-language="{}"><code>{}</code></pre>'.format(
                html.escape(language),
                html.escape(code),
            )
        )
        cursor = match.end()
    chunks.append(_format_plain_question_text(text[cursor:]))
    return mark_safe("".join(chunks))


def _format_plain_question_text(text: str) -> str:
    escaped = html.escape(text)
    escaped = _INLINE_CODE_RE.sub(r'<code class="question-inline-code">\1</code>', escaped)
    return escaped.replace("\n", "<br>")
