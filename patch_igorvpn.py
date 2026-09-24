#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, re, shutil, subprocess, sys
from pathlib import Path

APP_NAME = "Igor VPN"
SECTION_TITLE = "ОБХОД БЕЛЫХ СПИСКОВ"
WALLET = "UQD5zntOd45072mubVxMSKbNoAjeyCd2VXCWySWqb9ncRdqV"

def fail(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(1)

def find_root():
    here = Path.cwd().resolve()
    for root in [here / "OpenFlux", here]:
        if (root / "ios-app/OpenFlux/ContentView.swift").exists():
            return root
    for p in here.glob("*/OpenFlux"):
        if (p / "ios-app/OpenFlux/ContentView.swift").exists():
            return p
    fail("Не найден OpenFlux/ios-app/OpenFlux/ContentView.swift")

def match_brace(text, open_pos):
    depth = 0
    in_string = False
    esc = False
    i = open_pos
    while i < len(text):
        c = text[i]
        if in_string:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    fail("Не удалось разобрать фигурные скобки ContentView.swift")

def patch_content(path):
    text = path.read_text(encoding="utf-8")

    text = text.replace('"OpenFlux"', '"Igor VPN"')
    for old in ["Yandex Docs URL", "Mail.ru Docs URL", "Yandex.Docs URL", "Mail.ru.Docs URL", "Document URL"]:
        text = text.replace('"' + old + '"', '"' + SECTION_TITLE + '"')
    text = text.replace('"Yandex Docs"', '"' + SECTION_TITLE + '"')
    text = text.replace('"Yandex.Docs"', '"' + SECTION_TITLE + '"')

    if ".pickerStyle(.segmented)" in text and ".igorHiddenTransportPicker" not in text:
        text = text.replace(
            ".pickerStyle(.segmented)",
            ".pickerStyle(.segmented)\n"
            "                    .hidden() // .igorHiddenTransportPicker\n"
            "                    .frame(height: 0)"
        )

    if "showIgorSupport" not in text:
        m = re.search(r"struct\s+ContentView\s*:\s*View\s*\{", text)
        if not m:
            fail("Не найден struct ContentView: View")
        text = text[:m.end()] + "\n    @State private var showIgorSupport = false\n" + text[m.end():]

    if "SupportView()" not in text:
        m = re.search(r"var\s+body\s*:\s*some\s+View\s*\{", text)
        if not m:
            fail("Не найден var body: some View")
        body_open = text.find("{", m.start())
        body_close = match_brace(text, body_open)
        original = text[body_open + 1:body_close].strip("\n")

        wrapped = '''
        ZStack(alignment: .topTrailing) {
__ORIGINAL__

            Button {
                showIgorSupport = true
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "heart.fill")
                    Text("Поддержать")
                }
                .font(.subheadline.bold())
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(.ultraThinMaterial)
                .clipShape(Capsule())
            }
            .padding(.top, 8)
            .padding(.trailing, 12)
            .zIndex(100)
        }
        .sheet(isPresented: $showIgorSupport) {
            SupportView()
        }
'''
        wrapped = wrapped.replace("__ORIGINAL__", original)
        text = text[:body_open + 1] + wrapped + text[body_close:]

    path.write_text(text, encoding="utf-8")
    print("OK ContentView:", path)

def create_support_view(app_dir):
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

def force_mailru(path):
    if not path.exists():
        print("WARNING: нет", path)
        return
    text = path.read_text(encoding="utf-8")
    old = text

    text = re.sub(r'("transport"\s*:\s*)transport\.rawValue\b', r'\1"mailru"', text)
    text = re.sub(r'("transport"\s*:\s*)transport\b', r'\1"mailru"', text)
    text = re.sub(r'(providerConfiguration\[\s*"transport"\s*\]\s*=\s*)[^\n]+', r'\1"mailru"', text)

    lines = []
    for line in text.splitlines():
        if "transport" in line.lower():
            line = re.sub(r'"(?:yandex|oneme|max)"', '"mailru"', line)
        lines.append(line)
    text = "\n".join(lines) + ("\n" if old.endswith("\n") else "")

    if text != old:
        path.write_text(text, encoding="utf-8")
        print("OK forced mailru:", path)
    else:
        print("WARNING: transport assignment не найден в", path)

def patch_display_name(root):
    project = root / "ios-app/project.yml"
    if project.exists():
        text = project.read_text(encoding="utf-8")
        old = text
        if "INFOPLIST_KEY_CFBundleDisplayName" in text:
            text = re.sub(
                r'(INFOPLIST_KEY_CFBundleDisplayName\s*:\s*).+',
                r'\1"Igor VPN"',
                text
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

def find_icon(root):
    candidates = [
        Path.cwd() / "app-icon.png",
        Path(__file__).resolve().parent / "app-icon.png",
        root.parent / "app-icon.png",
        root / "app-icon.png",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None

def apply_icon(root):
    icon = find_icon(root)
    if icon is None:
        print("WARNING: app-icon.png не найден. Загрузи его в корень builder-репозитория.")
        return

    assets = list((root / "ios-app").rglob("Assets.xcassets"))
    if not assets:
        fail("Assets.xcassets не найден")
    iconset = assets[0] / "AppIcon.appiconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    if shutil.which("sips") is None:
        fail("sips не найден — этот шаг должен выполняться на macOS GitHub Actions")

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
            stdout=subprocess.DEVNULL
        )
        images.append({
            "idiom": idiom,
            "size": size,
            "scale": scale,
            "filename": filename
        })

    (iconset / "Contents.json").write_text(
        json.dumps({"images": images, "info": {"version": 1, "author": "xcode"}}, indent=2) + "\n",
        encoding="utf-8"
    )
    print("OK icon:", icon)

def main():
    root = find_root()
    app = root / "ios-app/OpenFlux"
    content = app / "ContentView.swift"
    vpn = app / "VPNController.swift"
    provider = root / "ios-app/OpenFluxTunnel/PacketTunnelProvider.swift"

    patch_content(content)
    create_support_view(app)
    force_mailru(vpn)
    force_mailru(provider)
    patch_display_name(root)
    apply_icon(root)

    print("")
    print("ГОТОВО:")
    print("- Igor VPN")
    print("- ОБХОД БЕЛЫХ СПИСКОВ")
    print("- Mail.ru transport")
    print("- MAX/Yandex picker скрыт")
    print("- Поддержать сверху")
    print("- USDT TON:", WALLET)
    print("- by Tsymbal")
    print("- app-icon.png применена")
    print("- текущий direct-domains patch не тронут")

if __name__ == "__main__":
    main()
