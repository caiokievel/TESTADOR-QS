from __future__ import annotations

from django import template


register = template.Library()


@register.filter
def get_item(value: dict, key: str):
    if not isinstance(value, dict):
        return None
    return value.get(key)
