#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Igor VPN"
SECTION_TITLE = "ОБХОД БЕЛЫХ СПИСКОВ"
WALLET = "UQD5zntOd45072mubVxMSKbNoAjeyCd2VXCWySWqb9ncRdqV"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_root() -> Path:
    here = Path.cwd().resolve()
    candidates = [here / "OpenFlux", here]
    candidates.extend(here.glob("*/OpenFlux"))
    for root in candidates:
        if (root / "ios-app" / "OpenFlux" / "ContentView.swift").exists():
            return root
    fail("Не найден OpenFlux/ios-app/OpenFlux/ContentView.swift")


def matching_brace(text: str, open_pos: int) -> int:
    depth = 0
    i = open_pos
    in_string = False
    escape = False
    line_comment = False
    block_comment = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "/" and nxt == "*":
                block_comment += 1
                i += 2
                continue
            if ch == "*" and nxt == "/":
                block_comment -= 1
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = 1
            i += 2
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("Unmatched brace")


def add_support_state(text: str) -> str:
    if "showIgorSupport" in text:
        return text
    m = re.search(r"struct\s+ContentView\s*:\s*View\s*\{", text)
    if not m:
        fail("Не найден struct ContentView: View")
    return text[:m.end()] + "\n    @State private var showIgorSupport = false\n" + text[m.end():]


def remove_top_right_custom_buttons(text: str) -> str:
    # Exact button injected by patch_openflux.py. Remove it from the top-right,
    # but keep the sheet/state so we can expose the editor in the middle.
    marker = "showDirectDomainsEditor = true"
    pos = text.find(marker)
    if pos < 0:
        return text

    start = text.rfind("Button {", 0, pos)
    end_marker = ".padding(.trailing, 10)"
    end = text.find(end_marker, pos)
    if start >= 0 and end >= 0:
        end += len(end_marker)
        if end < len(text) and text[end] == "\n":
            end += 1
        text = text[:start] + text[end:]
        print("OK: убрана верхняя правая кнопка «Прямые сайты»")
    else:
        print("WARNING: верхняя правая кнопка direct-domains не найдена точно")
    return text


def strip_following_modifiers(text: str, end: int, base_indent: int) -> int:
    pos = end
    n = len(text)
    while pos < n:
        line_end = text.find("\n", pos)
        if line_end == -1:
            line_end = n
        line = text[pos:line_end]
        stripped = line.strip()
        if not stripped:
            pos = min(line_end + 1, n)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent >= base_indent and stripped.startswith("."):
            pos = min(line_end + 1, n)
            continue
        break
    return pos


def support_block(indent: str) -> str:
    return f'''{indent}VStack(spacing: 8) {{
{indent}    Button {{
{indent}        showIgorSupport = true
{indent}    }} label: {{
{indent}        Text("❤️ Поддержать ❤️")
{indent}            .font(.headline)
{indent}            .frame(maxWidth: .infinity)
{indent}            .padding(.vertical, 4)
{indent}    }}
{indent}    .buttonStyle(.borderedProminent)
{indent}    .tint(.pink)

{indent}    Button {{
{indent}        showDirectDomainsEditor = true
{indent}    }} label: {{
{indent}        Label("Прямые сайты", systemImage: "arrow.triangle.branch")
{indent}            .font(.footnote)
{indent}    }}
{indent}    .buttonStyle(.plain)
{indent}    .foregroundColor(.secondary)
{indent}}}'''


def replace_system_vpn_block(text: str) -> str:
    anchor = text.find('"System VPN (all traffic)"')
    if anchor < 0:
        if 'Text("❤️ Поддержать ❤️")' in text:
            return text
        verbose = text.find('"Verbose log"')
        if verbose < 0:
            fail('Не найден блок "System VPN (all traffic)" или "Verbose log"')
        line_start = text.rfind("\n", 0, verbose) + 1
        indent = re.match(r"[ \t]*", text[line_start:]).group(0)
        print("WARNING: блок System VPN не найден; кнопка вставлена перед Verbose log")
        return text[:line_start] + support_block(indent) + "\n\n" + text[line_start:]

    candidates = []
    pattern = re.compile(r"\b(VStack|Group|Section)\s*(?:\([^{}\n]*\))?\s*\{")
    search_start = max(0, anchor - 7000)
    for m in pattern.finditer(text, search_start, anchor):
        open_brace = text.find("{", m.start(), m.end() + 1)
        if open_brace < 0:
            continue
        try:
            close = matching_brace(text, open_brace)
        except ValueError:
            continue
        if close <= anchor:
            continue
        chunk = text[m.start():close + 1]
        if "System VPN (all traffic)" in chunk and "Start VPN" in chunk:
            candidates.append((close - m.start(), m.start(), close + 1))

    if not candidates:
        fail("Не удалось безопасно определить контейнер System VPN / Start VPN")

    _, start, end = min(candidates, key=lambda item: item[0])
    line_start = text.rfind("\n", 0, start) + 1
    indent = re.match(r"[ \t]*", text[line_start:start]).group(0)
    end = strip_following_modifiers(text, end, len(indent))
    replacement = support_block(indent) + "\n"
    print("OK: System VPN / Start VPN заменён на «❤️ Поддержать ❤️»")
    return text[:start] + replacement + text[end:]


def add_support_sheet(text: str) -> str:
    if ".sheet(isPresented: $showIgorSupport)" in text:
        return text
    body = re.search(r"\bvar\s+body\s*:\s*some\s+View\s*\{", text)
    if not body:
        fail("Не найден ContentView.body")
    body_open = text.find("{", body.start())
    body_close = matching_brace(text, body_open)
    modifier = '''\n        .sheet(isPresented: $showIgorSupport) {
            SupportView()
        }\n'''
    return text[:body_close] + modifier + text[body_close:]


def patch_content_view(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace('Text("OpenFlux")', 'Text("Igor VPN")')
    text = text.replace('.navigationTitle("OpenFlux")', '.navigationTitle("Igor VPN")')
    for old in ("Yandex Docs URL", "Mail.ru Docs URL", "Yandex.Docs URL", "Mail.ru.Docs URL", "Document URL"):
        text = text.replace(f'"{old}"', f'"{SECTION_TITLE}"')
    text = text.replace('"Yandex Docs"', '"Mail.ru Docs"')
    text = text.replace('"Yandex.Docs"', '"Mail.ru Docs"')

    if ".pickerStyle(.segmented)" in text and ".igorHiddenTransportPicker" not in text:
        text = text.replace(
            ".pickerStyle(.segmented)",
            ".pickerStyle(.segmented)\n"
            "                    .hidden() // .igorHiddenTransportPicker\n"
            "                    .frame(height: 0)",
            1,
        )

    text = add_support_state(text)
    text = remove_top_right_custom_buttons(text)
    text = replace_system_vpn_block(text)
    text = add_support_sheet(text)
    path.write_text(text, encoding="utf-8")
    print("OK ContentView:", path)


def create_support_view(app_dir: Path) -> None:
    support = app_dir / "SupportView.swift"
    support.write_text(f'''import SwiftUI
import UIKit

struct SupportView: View {{
    @Environment(\\.dismiss) private var dismiss
    @State private var copied = false

    private let wallet = "{WALLET}"

    var body: some View {{
        NavigationView {{
            Form {{
                Section {{
                    VStack(spacing: 12) {{
                        Text("❤️")
                            .font(.system(size: 44))
                        Text("Поддержать разработку")
                            .font(.title2.bold())
                        Text("USDT · сеть TON")
                            .font(.headline)
                    }}
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                }}

                Section("Адрес USDT TON") {{
                    Text(wallet)
                        .font(.system(.footnote, design: .monospaced))
                        .textSelection(.enabled)
                    Button {{
                        UIPasteboard.general.string = wallet
                        copied = true
                    }} label: {{
                        Label(copied ? "Скопировано" : "Скопировать адрес",
                              systemImage: copied ? "checkmark.circle.fill" : "doc.on.doc")
                    }}
                }}

                Section {{
                    Text("by Tsymbal")
                        .frame(maxWidth: .infinity)
                        .foregroundColor(.secondary)
                }}
            }}
            .navigationTitle("Поддержать")
            .toolbar {{
                ToolbarItem(placement: .confirmationAction) {{
                    Button("Готово") {{ dismiss() }}
                }}
            }}
        }}
    }}
}}
''', encoding="utf-8")
    print("OK SupportView:", support)


def ensure_mailru_import(text: str) -> str:
    if '"openflux/transport/mailru"' in text:
        return text
    needle = '"openflux/transport"\n'
    if needle in text:
        return text.replace(needle, needle + '"openflux/transport/mailru"\n', 1)
    needle = '"openflux/transport/oneme"\n'
    if needle in text:
        return text.replace(needle, '"openflux/transport/mailru"\n' + needle, 1)
    fail("Не удалось добавить import openflux/transport/mailru")


def force_mailru_go_bridge(path: Path) -> None:
    if not path.exists():
        fail(f"Не найден {path}")
    text = path.read_text(encoding="utf-8")
    text = ensure_mailru_import(text)

    text, count = re.subn(
        r'tt\s*:=\s*C\.GoString\(transportType\)',
        'tt := "mailru"',
        text,
        count=1,
    )
    if count != 1 and 'tt := "mailru"' not in text:
        fail(f"Не удалось принудительно выставить mailru в {path.name}")

    if 'case "mailru":' not in text:
        match = re.search(r'(^[ \t]*)case\s+"oneme"\s*:', text, flags=re.M)
        if not match:
            fail(f'Не найден case "oneme" в {path.name}')
        indent = match.group(1)
        case_code = (
            f'{indent}case "mailru":\n'
            f'{indent}\tt = transport.NewCompressedTransport(mailru.NewMailruDocsTransport(docURL, config))\n\n'
        )
        text = text[:match.start()] + case_code + text[match.start():]

    text = text.replace(
        '// transportType: "yandex" or "oneme".',
        '// transportType: Igor VPN build is forced to "mailru".',
    )
    text = text.replace(
        '// url: Yandex.Docs document URL (yandex transport).',
        '// url: Mail.ru public document URL.',
    )
    path.write_text(text, encoding="utf-8")
    print("OK Mail.ru Go bridge:", path)


def patch_swift_transport_labels(root: Path) -> None:
    for folder in (root / "ios-app" / "OpenFlux", root / "ios-app" / "OpenFluxTunnel"):
        if not folder.exists():
            continue
        for path in folder.rglob("*.swift"):
            text = path.read_text(encoding="utf-8")
            original = text
            text = text.replace("via Yandex Docs", "via Mail.ru Docs")
            text = text.replace('"Yandex Docs"', '"Mail.ru Docs"')
            text = text.replace('"Yandex.Docs"', '"Mail.ru Docs"')
            text = re.sub(
                r'(providerConfiguration\[\s*"transport"\s*\]\s*=\s*)[^\n]+',
                r'\1"mailru"',
                text,
            )
            text = re.sub(
                r'("transport"\s*:\s*)transport(?:\.rawValue)?\b',
                r'\1"mailru"',
                text,
            )
            lines = []
            for line in text.splitlines():
                if "transport" in line.lower():
                    line = re.sub(r'"(?:yandex|oneme|max)"', '"mailru"', line, flags=re.I)
                lines.append(line)
            text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
            if text != original:
                path.write_text(text, encoding="utf-8")
                print("OK Swift Mail.ru labels/config:", path)


def patch_display_name(root: Path) -> None:
    project = root / "ios-app" / "project.yml"
    if not project.exists():
        return
    text = project.read_text(encoding="utf-8")
    original = text
    if "INFOPLIST_KEY_CFBundleDisplayName" in text:
        text = re.sub(
            r'(INFOPLIST_KEY_CFBundleDisplayName\s*:\s*).+',
            rf'\1"{APP_NAME}"',
            text,
        )
    else:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "PRODUCT_BUNDLE_IDENTIFIER" in line and "tunnel" not in line.lower():
                indent = re.match(r"\s*", line).group(0)
                lines.insert(i + 1, f'{indent}INFOPLIST_KEY_CFBundleDisplayName: "{APP_NAME}"')
                break
        text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    if text != original:
        project.write_text(text, encoding="utf-8")
        print("OK display name:", project)


def find_icon(root: Path) -> Path | None:
    for candidate in (
        Path.cwd() / "app-icon.png",
        Path(__file__).resolve().parent / "app-icon.png",
        root.parent / "app-icon.png",
        root / "app-icon.png",
    ):
        if candidate.exists():
            return candidate.resolve()
    return None


def apply_icon(root: Path) -> None:
    icon = find_icon(root)
    if icon is None:
        fail("app-icon.png не найден в корне builder-репозитория")
    asset_dirs = list((root / "ios-app").rglob("Assets.xcassets"))
    if not asset_dirs:
        fail("Assets.xcassets не найден")
    iconset = asset_dirs[0] / "AppIcon.appiconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    if shutil.which("sips") is None:
        fail("sips не найден — запускай этот патч на macOS GitHub Actions")

    specs = [
        ("iphone", "20x20", "2x", 40, "Icon-20@2x.png"),
        ("iphone", "20x20", "3x", 60, "Icon-20@3x.png"),
        ("iphone", "29x29", "2x", 58, "Icon-29@2x.png"),
        ("iphone", "29x29", "3x", 87, "Icon-29@3x.png"),
        ("iphone", "40x40", "2x", 80, "Icon-40@2x.png"),
        ("iphone", "40x40", "3x", 120, "Icon-40@3x.png"),
        ("iphone", "60x60", "2x", 120, "Icon-60@2x.png"),
        ("iphone", "60x60", "3x", 180, "Icon-60@3x.png"),
        ("ipad", "20x20", "1x", 20, "Icon-20@1x-ipad.png"),
        ("ipad", "20x20", "2x", 40, "Icon-20@2x-ipad.png"),
        ("ipad", "29x29", "1x", 29, "Icon-29@1x-ipad.png"),
        ("ipad", "29x29", "2x", 58, "Icon-29@2x-ipad.png"),
        ("ipad", "40x40", "1x", 40, "Icon-40@1x-ipad.png"),
        ("ipad", "40x40", "2x", 80, "Icon-40@2x-ipad.png"),
        ("ipad", "76x76", "1x", 76, "Icon-76@1x.png"),
        ("ipad", "76x76", "2x", 152, "Icon-76@2x.png"),
        ("ipad", "83.5x83.5", "2x", 167, "Icon-83.5@2x.png"),
        ("ios-marketing", "1024x1024", "1x", 1024, "Icon-1024@1x.png"),
    ]
    images = []
    for idiom, size, scale, px, filename in specs:
        output = iconset / filename
        subprocess.run(
            ["sips", "-z", str(px), str(px), str(icon), "--out", str(output)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        images.append({"idiom": idiom, "size": size, "scale": scale, "filename": filename})
    (iconset / "Contents.json").write_text(
        json.dumps({"images": images, "info": {"version": 1, "author": "xcode"}}, indent=2) + "\n",
        encoding="utf-8",
    )
    print("OK app icon:", icon)


def main() -> None:
    root = find_root()
    app_dir = root / "ios-app" / "OpenFlux"
    patch_content_view(app_dir / "ContentView.swift")
    create_support_view(app_dir)

    # Actual transport change, not just a UI rename.
    force_mailru_go_bridge(root / "export_ios.go")
    force_mailru_go_bridge(root / "export_ios_packet.go")
    patch_swift_transport_labels(root)

    patch_display_name(root)
    apply_icon(root)

    print("\nГОТОВО:")
    print("- Igor VPN")
    print("- ОБХОД БЕЛЫХ СПИСКОВ")
    print("- фактический транспорт: Mail.ru Docs")
    print("- Yandex/MAX selector скрыт")
    print("- System VPN / Start VPN убраны из интерфейса")
    print("- вместо них: ❤️ Поддержать ❤️")
    print("- USDT TON:", WALLET)
    print("- by Tsymbal")
    print("- верхняя правая лишняя кнопка убрана")
    print("- Прямые сайты доступны под кнопкой поддержки")
    print("- app-icon.png применена")
    print("\nВАЖНО: exit node должен быть запущен с --transport=mailru")
    print("и с тем же codec, что iOS bridge (legacy / NewCompressedTransport).")


if __name__ == "__main__":
    main()
