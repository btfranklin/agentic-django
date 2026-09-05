from __future__ import annotations

from django.template import Context, Template


def test_pretty_json_formats_and_escapes_template_values() -> None:
    template = Template(
        "{% load agentic_django_tags %}{{ value|pretty_json }}"
    )

    rendered = template.render(Context({"value": {"html": "<b>hello</b>"}}))

    assert rendered == '{\n  &quot;html&quot;: &quot;&lt;b&gt;hello&lt;/b&gt;&quot;\n}'
