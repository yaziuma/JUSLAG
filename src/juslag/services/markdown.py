from __future__ import annotations

import re


def markdown_to_html(markdown_text: str) -> str:
    escaped = (
        markdown_text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    lines = escaped.splitlines()
    html: list[str] = []
    in_code = False
    in_list = False
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code:
                html.append("<pre><code>")
                in_code = True
            else:
                html.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            html.append(line)
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                html.append("<table class='table table-sm'><tbody>")
                in_table = True
            if re.match(r"^\|\s*[-:]+\s*(\|\s*[-:]+\s*)+\|$", stripped):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            html.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        elif in_table:
            html.append("</tbody></table>")
            in_table = False

        if stripped.startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{stripped[2:]}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False

        if stripped.startswith("### "):
            html.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            html.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            html.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped:
            html.append(f"<p>{stripped}</p>")

    if in_list:
        html.append("</ul>")
    if in_code:
        html.append("</code></pre>")
    if in_table:
        html.append("</tbody></table>")
    return "\n".join(html)
