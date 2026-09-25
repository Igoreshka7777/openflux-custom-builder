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


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_root() -> Path:
    here = Path.cwd().resolve()
    candidates = [here / "OpenFlux", here]
    candidates += list(here.glob("*/OpenFlux"))
    for root in candidates:
        if (root / "ios-app/OpenFlux/ContentView.swift").exists():
            return root
    fail("Не найден OpenFlux/ios-app/OpenFlux/ContentView.swift")


def matching_brace(text: str, open_pos: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    line_comment = False
    block_comment = 0
    i = open_pos
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if c == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if c == "/" and n == "*":
                block_comment += 1
                i += 2
                continue
            if c == "*" and n == "/":
                block_comment -= 1
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == "/" and n == "/":
            line_comment = True
            i += 2
            continue
        if c == "/" and n == "*":
            block_comment = 1
            i += 2
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    fail("Не удалось найти закрывающую фигурную скобку")


def remove_about_button(text: str) -> str:
    """
    Полностью убирает кнопку "О приложении" / info.circle из правого верхнего угла.
    Сначала удаляем ToolbarItem целиком; затем обрабатываем Button { } label: { }.
    """
    removed = False

    # 1) Наиболее частый вариант: кнопка находится внутри ToolbarItem.
    toolbar_pat = re.compile(r"\bToolbarItem\s*(?:\([^{}]*\))?\s*\{")
    matches = list(toolbar_pat.finditer(text))

    for m in reversed(matches):
        open_pos = text.find("{", m.start(), m.end())
        if open_pos < 0:
            continue

        close_pos = matching_brace(text, open_pos)
        block = text[m.start():close_pos + 1]

        if (
            "info.circle" in block
            or "showAbout" in block
            or "showingAbout" in block
            or "О приложении" in block
        ):
            end = close_pos + 1
            while end < len(text) and text[end] in " \t":
                end += 1
            if end < len(text) and text[end] == "\n":
                end += 1

            text = text[:m.start()] + text[end:]
            removed = True

    # 2) Если кнопка была не в toolbar, удаляем обычный
    #    Button { ... } label: { Image(systemName: "info.circle") ... }.
    button_pat = re.compile(r"\bButton\s*\{")
    matches = list(button_pat.finditer(text))

    for m in reversed(matches):
        action_open = text.find("{", m.start(), m.end())
        if action_open < 0:
            continue

        action_close = matching_brace(text, action_open)

        p = action_close + 1
        while p < len(text) and text[p].isspace():
            p += 1

        if not text.startswith("label:", p):
            continue

        label_open = text.find("{", p)
        if label_open < 0:
            continue

        label_close = matching_brace(text, label_open)
        block = text[m.start():label_close + 1]

        if (
            "info.circle" not in block
            and "showAbout" not in block
            and "showingAbout" not in block
            and "О приложении" not in block
        ):
            continue

        start = m.start()
        end = label_close + 1

        # Убираем простые модификаторы этой кнопки на следующих строках.
        while True:
            q = end
            while q < len(text) and text[q] in " \t":
                q += 1

            if q < len(text) and text[q] == "\n":
                q += 1
                r = q
                while r < len(text) and text[r] in " \t":
                    r += 1

                if r < len(text) and text[r] == ".":
                    line_end = text.find("\n", r)
                    end = len(text) if line_end < 0 else line_end + 1
                    continue

            break

        text = text[:start] + text[end:]
        removed = True

    if removed:
        print("OK: верхняя кнопка 'О приложении' удалена")
    else:
        print("INFO: кнопка 'О приложении' / info.circle не найдена")

    return text



def enclosing_blocks(text: str, pos: int):
    candidates = []
    patterns = [
        ("Section", r"\bSection\s*(?:\([^{}]*\))?\s*\{"),
        ("GroupBox", r"\bGroupBox\s*(?:\([^{}]*\))?\s*\{"),
        ("VStack", r"\bVStack\s*(?:\([^{}]*\))?\s*\{"),
        ("Group", r"\bGroup\s*\{"),
    ]
    for kind, pat in patterns:
        for m in re.finditer(pat, text[:pos], flags=re.S):
            open_pos = text.find("{", m.start(), m.end())
            if open_pos < 0:
                continue
            close_pos = matching_brace(text, open_pos)
            if open_pos < pos < close_pos:
                candidates.append((kind, m.start(), open_pos, close_pos))
    return candidates


def remove_system_vpn_block(text: str) -> str:
    marker_pos = text.find('"System VPN (all traffic)"')
    if marker_pos < 0:
        marker_pos = text.find('"Start VPN"')
    if marker_pos < 0:
        print("INFO: System VPN block not found")
        return text

    blocks = enclosing_blocks(text, marker_pos)
    if not blocks:
        print("WARNING: System VPN container not identified")
        return text

    preferred = [b for b in blocks if b[0] in ("Section", "GroupBox")]
    chosen = max(preferred, key=lambda x: x[1]) if preferred else min(blocks, key=lambda x: x[1])

    kind, start, _, close = chosen
    end = close + 1
    while end < len(text) and text[end] in " \t":
        end += 1
    if end < len(text) and text[end] == "\n":
        end += 1

    print(f"Removed System VPN UI block: {kind}")
    return text[:start] + text[end:]


def add_support_state(text: str) -> str:
    if "showIgorSupport" in text:
        return text
    m = re.search(r"struct\s+ContentView\s*:\s*View\s*\{", text)
    if not m:
        fail("Не найден struct ContentView: View")
    return text[:m.end()] + "\n    @State private var showIgorSupport = false\n" + text[m.end():]


def add_support_button_inside_content(text: str) -> str:
    if 'Label("Поддержать", systemImage: "heart.fill")' in text:
        return text

    button = '''
            Button {
                showIgorSupport = true
            } label: {
                Label("Поддержать", systemImage: "heart.fill")
                    .font(.headline)
            }
            .buttonStyle(.plain)
            .padding(.vertical, 8)

'''

    for marker in ['Text("Verbose log")', 'Text("Лог")', 'Text("Logs")']:
        p = text.find(marker)
        if p >= 0:
            line_start = text.rfind("\n", 0, p) + 1
            return text[:line_start] + button + text[line_start:]

    m = re.search(r"var\s+body\s*:\s*some\s+View\s*\{", text)
    if not m:
        fail("Не найден var body: some View")
    open_pos = text.find("{", m.start(), m.end())
    return text[:open_pos + 1] + "\n" + button + text[open_pos + 1:]


def add_support_sheet(text: str) -> str:
    if ".sheet(isPresented: $showIgorSupport)" in text:
        return text

    m = re.search(r"var\s+body\s*:\s*some\s+View\s*\{", text)
    if not m:
        fail("Не найден var body: some View")

    body_open = text.find("{", m.start(), m.end())
    body_close = matching_brace(text, body_open)
    original = text[body_open + 1:body_close].strip("\n")

    replacement = '''
        Group {
__ORIGINAL__
        }
        .sheet(isPresented: $showIgorSupport) {
            SupportView()
        }
'''.replace("__ORIGINAL__", original)

    return text[:body_open + 1] + replacement + text[body_close:]


def patch_content_view(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    # Убираем круглую кнопку "О приложении" справа сверху.
    text = remove_about_button(text)

    text = text.replace('"OpenFlux"', '"Igor VPN"')
    for old in (
        "Yandex Docs URL",
        "Mail.ru Docs URL",
        "Yandex.Docs URL",
        "Mail.ru.Docs URL",
        "Document URL",
        "Yandex Docs",
        "Yandex.Docs",
        "Mail.ru Docs",
    ):
        text = text.replace(f'"{old}"', f'"{SECTION_TITLE}"')

    if ".pickerStyle(.segmented)" in text and ".igorHiddenTransportPicker" not in text:
        text = text.replace(
            ".pickerStyle(.segmented)",
            ".pickerStyle(.segmented)\n"
            "                    .hidden() // .igorHiddenTransportPicker\n"
            "                    .frame(height: 0)"
        )

    text = remove_system_vpn_block(text)
    text = add_support_state(text)
    text = add_support_button_inside_content(text)
    text = add_support_sheet(text)

    path.write_text(text, encoding="utf-8")
    print("OK ContentView:", path)


def create_support_view(app_dir: Path) -> None:
    support = app_dir / "SupportView.swift"
    content = '''import SwiftUI
import UIKit

struct SupportView: View {
    @Environment(\\.dismiss) private var dismiss
    @State private var copied = false

    private let wallet = "__WALLET__"

    var body: some View {
        NavigationView {
            Form {
                Section {
                    VStack(spacing: 10) {
                        Image(systemName: "heart.fill")
                            .font(.system(size: 38))
                            .foregroundStyle(.pink)

                        Text("Поддержать разработку")
                            .font(.title2.bold())

                        Text("USDT · сеть TON")
                            .font(.headline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                }

                Section("Адрес кошелька") {
                    Text(wallet)
                        .font(.system(.footnote, design: .monospaced))
                        .textSelection(.enabled)

                    Button {
                        UIPasteboard.general.string = wallet
                        copied = true
                    } label: {
                        Label(
                            copied ? "Скопировано" : "Скопировать адрес",
                            systemImage: copied ? "checkmark.circle.fill" : "doc.on.doc"
                        )
                    }
                }

                Section {
                    Text("by Tsymbal")
                        .frame(maxWidth: .infinity)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Поддержать")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") {
                        dismiss()
                    }
                }
            }
        }
    }
}
'''.replace("__WALLET__", WALLET)
    support.write_text(content, encoding="utf-8")
    print("OK SupportView:", support)


MAILRU_BYPASS_SWIFT = r'''
    private static func resolveMailruIPv4(_ host: String) -> [String] {
        var hints = addrinfo(
            ai_flags: AI_ADDRCONFIG,
            ai_family: AF_INET,
            ai_socktype: SOCK_STREAM,
            ai_protocol: IPPROTO_TCP,
            ai_addrlen: 0,
            ai_canonname: nil,
            ai_addr: nil,
            ai_next: nil
        )

        var result: UnsafeMutablePointer<addrinfo>?

        guard getaddrinfo(host, nil, &hints, &result) == 0,
              let first = result else {
            return []
        }

        defer { freeaddrinfo(result) }

        var ips: [String] = []
        var ptr: UnsafeMutablePointer<addrinfo>? = first

        while let info = ptr {
            if info.pointee.ai_family == AF_INET,
               let addr = info.pointee.ai_addr {

                var sin = addr.withMemoryRebound(
                    to: sockaddr_in.self,
                    capacity: 1
                ) { $0.pointee }

                var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))

                inet_ntop(
                    AF_INET,
                    &sin.sin_addr,
                    &buffer,
                    socklen_t(INET_ADDRSTRLEN)
                )

                let ip = String(cString: buffer)
                if !ips.contains(ip) {
                    ips.append(ip)
                }
            }

            ptr = info.pointee.ai_next
        }

        return ips
    }

    static let bypassRoutes: [NEIPv4Route] = {
        var routes: [NEIPv4Route] = []

        let mailHosts = [
            "cloud.mail.ru",
            "docs.datacloudmail.ru",
            "mail.ru"
        ]

        for host in mailHosts {
            for ip in resolveMailruIPv4(host) {
                routes.append(
                    NEIPv4Route(
                        destinationAddress: ip,
                        subnetMask: "255.255.255.255"
                    )
                )
            }
        }

        routes.append(
            NEIPv4Route(
                destinationAddress: "95.165.48.30",
                subnetMask: "255.255.255.255"
            )
        )

        routes.append(
            NEIPv4Route(
                destinationAddress: "8.8.8.8",
                subnetMask: "255.255.255.255"
            )
        )

        routes.append(
            NEIPv4Route(
                destinationAddress: "1.1.1.1",
                subnetMask: "255.255.255.255"
            )
        )

        return routes
    }()
'''


def replace_bypass_routes(text: str) -> str:
    p = text.find("static let bypassRoutes")
    if p < 0:
        m = re.search(
            r"class\s+PacketTunnelProvider\s*:\s*NEPacketTunnelProvider\s*\{",
            text,
        )
        if not m:
            fail("Не найден class PacketTunnelProvider")
        return text[:m.end()] + "\n" + MAILRU_BYPASS_SWIFT + "\n" + text[m.end():]

    open_pos = text.find("{", p)
    if open_pos < 0:
        fail("Не найдено начало bypassRoutes")

    close_pos = matching_brace(text, open_pos)
    end = close_pos + 1
    if text[end:end+2] == "()":
        end += 2

    return text[:p] + MAILRU_BYPASS_SWIFT.strip("\n") + text[end:]


def patch_packet_tunnel(path: Path) -> None:
    if not path.exists():
        fail(f"Не найден {path}")

    text = path.read_text(encoding="utf-8")

    if "import Foundation" not in text:
        text = text.replace(
            "import NetworkExtension",
            "import NetworkExtension\nimport Foundation\nimport Darwin",
            1,
        )
    elif "import Darwin" not in text:
        text = text.replace("import Foundation", "import Foundation\nimport Darwin", 1)

    text = replace_bypass_routes(text)

    text = re.sub(
        r'let\s+transport\s*=\s*\(conf\["transport"\]\s+as\?\s+String\)\s*\?\?\s*"[^"]+"',
        'let transport = (conf["transport"] as? String) ?? "mailru"',
        text,
    )

    text = text.replace("the Yandex backend the", "the Mail.ru backend the")
    text = text.replace(
        "Exclude the transport's own backend (Yandex ranges)",
        "Exclude the transport's own Mail.ru backend"
    )

    path.write_text(text, encoding="utf-8")
    print("OK PacketTunnelProvider:", path)


def force_mailru_in_vpn_controller(path: Path) -> None:
    if not path.exists():
        print("WARNING: VPNController.swift не найден")
        return

    text = path.read_text(encoding="utf-8")
    old = text

    text = re.sub(
        r'("transport"\s*:\s*)transport\.rawValue\b',
        r'\1"mailru"',
        text,
    )
    text = re.sub(
        r'("transport"\s*:\s*)transport\b',
        r'\1"mailru"',
        text,
    )
    text = re.sub(
        r'(providerConfiguration\[\s*"transport"\s*\]\s*=\s*)[^\n]+',
        r'\1"mailru"',
        text,
    )

    lines = []
    for line in text.splitlines():
        if "transport" in line.lower():
            line = re.sub(
                r'"(?:yandex|yandexdocs|yandex_docs|oneme|max)"',
                '"mailru"',
                line,
                flags=re.I,
            )
        lines.append(line)

    text = "\n".join(lines) + ("\n" if old.endswith("\n") else "")
    path.write_text(text, encoding="utf-8")
    print("OK Mail.ru in VPNController:", path)


def patch_display_name(root: Path) -> None:
    project = root / "ios-app/project.yml"
    if not project.exists():
        return

    text = project.read_text(encoding="utf-8")
    old = text

    if "INFOPLIST_KEY_CFBundleDisplayName" in text:
        text = re.sub(
            r'(INFOPLIST_KEY_CFBundleDisplayName\s*:\s*).+',
            r'\1"Igor VPN"',
            text,
        )
    else:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "PRODUCT_BUNDLE_IDENTIFIER" in line and "tunnel" not in line.lower():
                indent = re.match(r"\s*", line).group(0)
                lines.insert(i + 1, indent + 'INFOPLIST_KEY_CFBundleDisplayName: "Igor VPN"')
                break
        text = "\n".join(lines) + ("\n" if old.endswith("\n") else "")

    if text != old:
        project.write_text(text, encoding="utf-8")
        print("OK display name:", project)


def find_icon(root: Path):
    for p in [
        Path.cwd() / "app-icon.png",
        Path(__file__).resolve().parent / "app-icon.png",
        root.parent / "app-icon.png",
        root / "app-icon.png",
    ]:
        if p.exists():
            return p.resolve()
    return None


def apply_icon(root: Path) -> None:
    icon = find_icon(root)
    if icon is None:
        print("WARNING: app-icon.png не найден")
        return

    assets = list((root / "ios-app").rglob("Assets.xcassets"))
    if not assets:
        fail("Assets.xcassets не найден")

    iconset = assets[0] / "AppIcon.appiconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True, exist_ok=True)

    if shutil.which("sips") is None:
        fail("sips не найден — запускать на macOS GitHub runner")

    specs = [
        ("iphone","20x20","2x",40,"Icon-20@2x.png"),
        ("iphone","20x20","3x",60,"Icon-20@3x.png"),
        ("iphone","29x29","2x",58,"Icon-29@2x.png"),
        ("iphone","29x29","3x",87,"Icon-29@3x.png"),
        ("iphone","40x40","2x",80,"Icon-40@2x.png"),
        ("iphone","40x40","3x",120,"Icon-40@3x.png"),
        ("iphone","60x60","2x",120,"Icon-60@2x.png"),
        ("iphone","60x60","3x",180,"Icon-60@3x.png"),
        ("ipad","20x20","1x",20,"Icon-20@1x-ipad.png"),
        ("ipad","20x20","2x",40,"Icon-20@2x-ipad.png"),
        ("ipad","29x29","1x",29,"Icon-29@1x-ipad.png"),
        ("ipad","29x29","2x",58,"Icon-29@2x-ipad.png"),
        ("ipad","40x40","1x",40,"Icon-40@1x-ipad.png"),
        ("ipad","40x40","2x",80,"Icon-40@2x-ipad.png"),
        ("ipad","76x76","1x",76,"Icon-76@1x.png"),
        ("ipad","76x76","2x",152,"Icon-76@2x.png"),
        ("ipad","83.5x83.5","2x",167,"Icon-83.5@2x.png"),
        ("ios-marketing","1024x1024","1x",1024,"Icon-1024@1x.png"),
    ]

    images = []
    for idiom, size, scale, px, filename in specs:
        out = iconset / filename
        subprocess.run(
            ["sips", "-z", str(px), str(px), str(icon), "--out", str(out)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        images.append({
            "idiom": idiom,
            "size": size,
            "scale": scale,
            "filename": filename,
        })

    (iconset / "Contents.json").write_text(
        json.dumps(
            {"images": images, "info": {"version": 1, "author": "xcode"}},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print("OK icon:", icon)


def main() -> None:
    root = find_root()

    patch_content_view(root / "ios-app/OpenFlux/ContentView.swift")
    create_support_view(root / "ios-app/OpenFlux")
    force_mailru_in_vpn_controller(root / "ios-app/OpenFlux/VPNController.swift")
    patch_packet_tunnel(root / "ios-app/OpenFluxTunnel/PacketTunnelProvider.swift")
    patch_display_name(root)
    apply_icon(root)

    print("")
    print("ГОТОВО:")
    print("- Igor VPN")
    print("- ОБХОД БЕЛЫХ СПИСКОВ")
    print("- Mail.ru transport")
    print("- Mail.ru bypass")
    print("- System VPN / Start VPN удалены из интерфейса")
    print("- верхняя кнопка О приложении удалена")
    print("- Поддержать находится внутри экрана")
    print("- USDT TON:", WALLET)
    print("- by Tsymbal")
    print("- app-icon.png применяется автоматически")


if __name__ == "__main__":
    main()
