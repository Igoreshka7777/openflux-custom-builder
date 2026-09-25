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
DEFAULT_DIRECT_DOMAINS = """sberbank.ru
tbank.ru
vtb.ru
alfabank.ru
gazprombank.ru
rshb.ru
sovcombank.ru
otpbank.ru
raiffeisen.ru
rosbank.ru
mtsbank.ru
pochtabank.ru
uralsib.ru
akbars.ru
bspb.ru
rencredit.ru
ozonbank.ru
yandexbank.ru
wildberries.ru
wb.ru
avito.ru
ozon.ru
yandex.ru
ya.ru
vk.com
vk.ru
mail.ru
rutube.ru
dzen.ru
gosuslugi.ru
2gis.ru
hh.ru
youla.ru
kuper.ru
samokat.ru
magnit.ru
megamarket.ru
dns-shop.ru
citilink.ru
mvideo.ru
eldorado.ru
lamoda.ru
kinopoisk.ru
rbc.ru
lenta.ru"""


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


def remove_system_vpn_property(text: str) -> str:
    # A previous version removed only the VStack inside this computed property,
    # leaving `private var vpnSection: some View { }` which Swift cannot compile.
    m = re.search(r'\bprivate\s+var\s+vpnSection\s*:\s*some\s+View\s*\{', text)
    if m:
        start = m.start()
        close = matching_brace(text, text.find('{', m.start(), m.end()))
        text = text[:start] + text[close + 1:]
    text = re.sub(r'^\s*vpnSection\s*\n', '', text, flags=re.M)
    return text


def add_support_state(text: str) -> str:
    if "showIgorSupport" in text:
        return text
    m = re.search(r"struct\s+ContentView\s*:\s*View\s*\{", text)
    if not m:
        fail("Не найден struct ContentView: View")
    return text[:m.end()] + "\n    @State private var showIgorSupport = false\n" + text[m.end():]


def add_support_button_inside_content(text: str) -> str:
    if 'Text("Поддержать").font(.headline)' in text:
        return text

    button = '''
            Button {
                showIgorSupport = true
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "heart.fill").foregroundStyle(.pink)
                    Spacer(minLength: 0)
                    Text("Поддержать").font(.headline)
                    Spacer(minLength: 0)
                    Image(systemName: "heart.fill").foregroundStyle(.pink)
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)
            .padding(.vertical, 8)

'''

    # Insert as a sibling of Toggle, never into its label closure.
    m = re.search(r'\bprivate\s+var\s+logView\s*:\s*some\s+View\s*\{\s*VStack\s*\([^{}]*\)\s*\{', text)
    if m:
        return text[:m.end()] + '\n' + button + text[m.end():]

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


def replace_swift_property(text: str, name: str, replacement: str) -> str:
    m = re.search(r'\bprivate\s+var\s+' + re.escape(name) +
                  r'\s*:\s*some\s+View\s*\{', text)
    if not m:
        fail(f"Не найден блок {name} в ContentView.swift")
    close = matching_brace(text, text.find('{', m.start(), m.end()))
    return text[:m.start()] + replacement + text[close + 1:]


VPN_CONTROLS = '''private var controls: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                if vpn.active {
                    Button(role: .destructive) { vpn.stop() } label: {
                        Label("Stop", systemImage: "stop.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                } else {
                    Button {
                        vpn.start(transport: "mailru", url: docURL,
                                  maxToken: "", maxUid: "",
                                  igorDirectDomainsText: directDomains)
                    } label: {
                        Label("Start", systemImage: "play.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!canStart)
                }
                Button { testSystemVPN() } label: {
                    Label("Test", systemImage: "network").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(vpn.status != "Connected")
            }
            if !vpnTestResult.isEmpty {
                Text(vpnTestResult).font(.footnote).textSelection(.enabled)
            }
            if vpn.status.hasPrefix("Error:") {
                Text(vpn.status).font(.footnote).foregroundColor(.red)
            }
        }
    }'''


VPN_HEADER = '''private var statusHeader: some View {
        HStack {
            Circle()
                .fill(vpn.status == "Connected" ? Color.green : (vpn.active ? Color.orange : Color.gray))
                .frame(width: 12, height: 12)
            Text(vpn.status == "Connected" ? "Connected" :
                 (vpn.active ? "Connecting…" : "Stopped"))
                .font(.headline)
            Spacer()
        }
    }'''


VPN_LOG = '''private var logView: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("VPN: \\(vpn.status)")
                .font(.footnote)
                .frame(maxWidth: .infinity, alignment: .center)
            HStack {
                Text("Логи VPN").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button { vpn.refreshLog() } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .accessibilityLabel("Обновить логи")
                Button { UIPasteboard.general.string = vpn.log } label: {
                    Image(systemName: "doc.on.doc")
                }
                .accessibilityLabel("Скопировать логи")
            }
            ScrollViewReader { reader in
                ScrollView {
                    Text(vpn.log.isEmpty ? "Ожидание событий VPN…" : vpn.log)
                        .font(.system(.caption2, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .id("vpnLogTail")
                }
                .onChange(of: vpn.log) { _ in
                    reader.scrollTo("vpnLogTail", anchor: .bottom)
                }
            }
            .frame(height: 220)
            .padding(8)
            .background(Color(.secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in
            vpn.refreshLog()
        }
    }'''


VPN_TEST = '''
    private func testSystemVPN() {
        vpnTestResult = "Проверка IP…"
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        // No proxy: this request follows the iPhone's system route.
        let session = URLSession(configuration: configuration)
        guard let url = URL(string: "https://api.ipify.org") else { return }
        session.dataTask(with: url) { data, _, error in
            DispatchQueue.main.async {
                if let error = error {
                    vpnTestResult = "Ошибка: \\(error.localizedDescription)"
                } else if let data = data, let ip = String(data: data, encoding: .utf8) {
                    vpnTestResult = "Внешний IP: \\(ip.trimmingCharacters(in: .whitespacesAndNewlines))"
                } else {
                    vpnTestResult = "Нет ответа от сервера проверки"
                }
            }
        }.resume()
    }
'''


def patch_content_view(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    # The picker is hidden, so an old @AppStorage value must not select Yandex.
    # Force the actual transport passed to TunnelController, not just its label.
    text, count = re.subn(
        r'TransportKind\(rawValue:\s*transportRaw\)\s*\?\?\s*\.yandex',
        '.mailru', text,
    )
    if not count and not re.search(r'private var transport:\s*TransportKind\s*\{\s*\.mailru\s*\}', text):
        fail("Не найден выбор транспорта в ContentView.swift")
    text = re.sub(r'@AppStorage\("transportKind"\)\s+private var transportRaw:\s*String\s*=\s*TransportKind\.yandex\.rawValue',
                  '@AppStorage("transportKind") private var transportRaw: String = TransportKind.mailru.rawValue', text)
    text, count = re.subn(r'(case \.yandex:\s*return !docURL\.trimmingCharacters\(in: \.whitespaces\)\.isEmpty)',
                          r'\1\n        case .mailru: return !docURL.trimmingCharacters(in: .whitespaces).isEmpty', text, count=1)
    if count != 1 and 'case .mailru: return !docURL' not in text:
        fail("Не найдена проверка URL в ContentView.swift")
    text, count = re.subn(r'(case \.yandex:\s*\n\s*field\(title: "Yandex Docs URL",\s*\n\s*placeholder: "[^"]+",\s*\n\s*text: \$docURL\))',
                          r'\1\n        case .mailru:\n            field(title: "ОБХОД БЕЛЫХ СПИСКОВ",\n                  placeholder: "https://cloud.mail.ru/public/...",\n                  text: $docURL)', text, count=1)
    if count != 1 and 'case .mailru:' not in text:
        fail("Не найдено поле URL в ContentView.swift")

    # Убираем круглую кнопку "О приложении" справа сверху.
    text = remove_about_button(text)
    text = re.sub(r'\s*\.toolbar\s*\{\s*\}', '', text)
    text = re.sub(r'\s*\.sheet\(isPresented:\s*\$showInfo\)\s*\{\s*InfoView\(\)\s*\}', '', text)

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
    text = remove_system_vpn_property(text)
    text = text.replace('.disabled(tunnel.running)', '.disabled(vpn.active)')
    # The visible Start button controls the actual iOS packet tunnel.
    text = replace_swift_property(text, "controls", VPN_CONTROLS)
    text = replace_swift_property(text, "statusHeader", VPN_HEADER)
    text = replace_swift_property(text, "logView", VPN_LOG)
    if 'import UIKit' not in text:
        text = text.replace('import SwiftUI', 'import SwiftUI\nimport UIKit', 1)
    if 'import Combine' not in text:
        text = text.replace('import SwiftUI', 'import SwiftUI\nimport Combine', 1)
    if re.search(r'\bprivate\s+var\s+portField\s*:\s*some\s+View\s*\{', text):
        text = replace_swift_property(text, "portField", '')
    text = re.sub(r'^\s*portField\s*\n', '', text, flags=re.M)
    if 'private func testSystemVPN()' not in text:
        m = re.search(r'\bprivate\s+func\s+field\(', text)
        if not m:
            fail("Не найдена точка вставки проверки VPN в ContentView.swift")
        text = text[:m.start()] + VPN_TEST + '\n    ' + text[m.start():]
    if '@State private var vpnTestResult' not in text:
        m = re.search(r'\bstruct\s+ContentView\s*:\s*View\s*\{', text)
        text = text[:m.end()] + '\n    @State private var vpnTestResult = ""\n' + text[m.end():]
    text = re.sub(r'guard \(Int\(socksPort\) \?\? 0\) > 0 else \{ return false \}',
                  '', text)
    text = add_support_state(text)
    text = add_support_button_inside_content(text)
    text = add_support_sheet(text)
    # The top-right branch button and its editor use the "directDomains"
    # setting. Populate that setting, which is also passed to the VPN.
    if 'showDirectDomainsEditor = true' not in text or 'DirectDomainsEditor(text: $directDomains)' not in text:
        fail("Не найдена существующая верхняя кнопка «Прямые сайты»; сначала примените patch_openflux-fixed.py")
    default = json.dumps(DEFAULT_DIRECT_DOMAINS, ensure_ascii=False)
    text, default_count = re.subn(
        r'(@AppStorage\("directDomains"\)\s+private\s+var\s+directDomains\s*:\s*String\s*=\s*)""',
        lambda m: m.group(1) + default, text, count=1,
    )
    if not default_count and '@AppStorage("directDomains") private var directDomains: String = ' not in text:
        fail("Не найдено хранение списка верхней кнопки")
    # Clean up copies already modified by the earlier Igor script.
    text = re.sub(r'(?m)^\s*@State private var showIgorDirectDomains = false\n', '', text)
    text = re.sub(r'(?m)^\s*@AppStorage\("igorDirectDomainsText"\) private var igorDirectDomainsText = .*\n', '', text)
    text = re.sub(r'\s*\.sheet\(isPresented: \$showIgorDirectDomains\) \{\s*DirectDomainsEditor\(domains: \$igorDirectDomainsText\)\s*\}', '', text)

    path.write_text(text, encoding="utf-8")
    print("OK ContentView:", path)


def create_support_view(app_dir: Path) -> None:
    support = app_dir / "SupportView.swift"
    content = '''import SwiftUI
import UIKit

struct SupportView: View {
    @Environment(\\.dismiss) private var dismiss
    @State private var copied = false

    var body: some View {
        NavigationView {
            VStack(spacing: 24) {
                Spacer()
                Image(systemName: "heart.fill")
                    .font(.system(size: 52))
                    .foregroundStyle(.pink)
                Text("Поддержать Igor VPN")
                    .font(.title2.bold())
                VStack(spacing: 14) {
                    Text("ОТП Банк")
                        .font(.headline)
                        .foregroundStyle(.secondary)
                    Text("8 912 643-87-81")
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                        .minimumScaleFactor(0.7)
                        .lineLimit(1)
                        .textSelection(.enabled)
                    Button {
                        UIPasteboard.general.string = "89126438781"
                        copied = true
                    } label: {
                        Label(copied ? "Скопировано" : "Скопировать номер",
                              systemImage: copied ? "checkmark" : "doc.on.doc")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding(24)
                .frame(maxWidth: .infinity)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24))
                Spacer()
            }
            .padding(24)
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
'''
    support.write_text(content, encoding="utf-8")
    qr = app_dir / "Assets.xcassets/SupportQR.imageset"
    if qr.exists():
        shutil.rmtree(qr)
    print("OK SupportView:", support)


def create_direct_domains_editor(app_dir: Path) -> None:
    editor = app_dir / "DirectDomainsEditor.swift"
    if editor.exists():
        print("OK: существующий редактор прямых сайтов сохранён:", editor)
        return
    editor.write_text('''import SwiftUI

struct DirectDomainsEditor: View {
    @Environment(\\.dismiss) private var dismiss
    @Binding var domains: String

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 12) {
                Text("По одному домену на строку. После изменения выключите и включите VPN.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                TextEditor(text: $domains)
                    .font(.system(.body, design: .monospaced))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled(true)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .padding()
            .navigationTitle("Прямые сайты")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { dismiss() }
                }
            }
        }
    }
}
''', encoding="utf-8")
    print("OK direct domains editor:", editor)


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

    private final class RouteAddresses {
        private let lock = NSLock()
        private var values: Set<String> = ["95.165.48.30", "8.8.8.8", "1.1.1.1"]

        func add(_ addresses: [String]) {
            lock.lock()
            values.formUnion(addresses)
            lock.unlock()
        }

        func snapshot() -> [String] {
            lock.lock()
            defer { lock.unlock() }
            return values.sorted()
        }
    }

    static func bypassRoutes(directDomains: String) -> [NEIPv4Route] {
        let entries = directDomains.components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }
        var hosts = Set(["cloud.mail.ru", "docs.datacloudmail.ru", "mail.ru"])
        for entry in entries {
            let domain = entry.replacingOccurrences(of: "https://", with: "")
                .replacingOccurrences(of: "http://", with: "")
                .components(separatedBy: "/")[0]
            guard !domain.isEmpty, !domain.contains(" "), !domain.contains("*") else { continue }
            hosts.insert(domain)
            if !domain.hasPrefix("www.") { hosts.insert("www." + domain) }
        }

        // Resolve the configured hosts concurrently. Each hostname still
        // completes before its IP routes are applied, so none are skipped.
        let started = Date()
        let queue = OperationQueue()
        queue.maxConcurrentOperationCount = 16
        let addresses = RouteAddresses()
        for host in hosts {
            queue.addOperation {
                addresses.add(resolveMailruIPv4(host))
            }
        }
        queue.waitUntilAllOperationsAreFinished()
        let resolved = addresses.snapshot()
        NSLog("[Igor VPN] direct routes: hosts=\(hosts.count), ips=\(resolved.count), dnsSeconds=\(Date().timeIntervalSince(started))")
        return resolved.map {
            NEIPv4Route(destinationAddress: $0, subnetMask: "255.255.255.255")
        }
    }
'''


def replace_bypass_routes(text: str) -> str:
    if ("private final class RouteAddresses" in text
            and "static func bypassRoutes(directDomains: String)" in text
            and "private static func resolveMailruIPv4" in text):
        return text
    # Avoid duplicating the route collector if this section is patched again.
    collector = text.find("private final class RouteAddresses")
    if collector >= 0:
        start = text.find("{", collector)
        end = matching_brace(text, start) + 1
        text = text[:collector] + text[end:]
    p = text.find("static let bypassRoutes")
    if p < 0:
        p = text.find("static func bypassRoutes(")
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
    if 'ipv4.excludedRoutes = Self.bypassRoutes(directDomains: igorDirectDomains)' not in text:
        text = text.replace('ipv4.excludedRoutes = Self.bypassRoutes',
                            'ipv4.excludedRoutes = Self.bypassRoutes(directDomains: igorDirectDomains)')
    if 'Self.bypassRoutes(directDomains: igorDirectDomains)' not in text:
        fail("Не найдена строка excludedRoutes в PacketTunnelProvider.swift")
    # The user's builder already has `directDomains` as [String]. Keep that
    # separate from the new editable text list to avoid redeclaration.
    text = re.sub(r'let\s+directDomains\s*=\s*\(conf\["directDomains"\]\s+as\?\s+String\)\s*\?\?\s*""',
                  'let igorDirectDomains = (conf["igorDirectDomainsText"] as? String) ?? ""', text)
    if 'let igorDirectDomains = (conf["igorDirectDomainsText"] as? String) ?? ""' not in text:
        marker = 'let url = (conf["url"] as? String) ?? ""'
        if marker not in text:
            fail("Не найден URL в конфигурации PacketTunnelProvider.swift")
        text = text.replace(marker, marker + '\n        let igorDirectDomains = (conf["igorDirectDomainsText"] as? String) ?? ""', 1)

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

    # The Network Extension receives the real iOS stop reason even when the
    # containing app is suspended. Preserve it in the device system log.
    if '[Igor VPN] tunnel stopped by iOS, reason=' not in text:
        marker = 'OpenFluxStopPacketTunnel()'
        if marker not in text:
            fail("Не найден stopTunnel для записи причины отключения")
        text = text.replace(marker,
                            'NSLog("[Igor VPN] tunnel stopped by iOS, reason=\\(reason.rawValue)")\n        ' + marker,
                            1)
    if '[Igor VPN] tunnel start failed, code=' not in text:
        marker = 'if rc != 0 {\n'
        if marker not in text:
            fail("Не найдена проверка ошибки запуска PacketTunnelProvider")
        text = text.replace(marker, marker +
                            '                NSLog("[Igor VPN] tunnel start failed, code=\\(rc)")\n', 1)

    if 'override func handleAppMessage(' not in text:
        cls = re.search(r'class\s+PacketTunnelProvider\s*:\s*NEPacketTunnelProvider\s*\{', text)
        if not cls:
            fail("Не найден класс VPN-расширения для передачи логов")
        ipc = r'''
    private var routeSummary = ""
    private var routeSummaryDelivered = false

    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        guard String(data: messageData, encoding: .utf8) == "logs" else {
            completionHandler?(nil)
            return
        }
        var lines = ""
        if !routeSummaryDelivered && !routeSummary.isEmpty {
            lines = routeSummary
            routeSummaryDelivered = true
        }
        if let ptr = OpenFluxReadLog() {
            let goLog = String(cString: ptr)
            OpenFluxFreeString(ptr)
            if !goLog.isEmpty {
                if !lines.isEmpty { lines += "\n" }
                lines += goLog
            }
        }
        completionHandler?(Data(lines.utf8))
    }
'''
        text = text[:cls.end()] + ipc + text[cls.end():]
    if 'routeSummary = "Прямых IP-маршрутов:' not in text:
        marker = 'ipv4.excludedRoutes = Self.bypassRoutes(directDomains: igorDirectDomains)'
        text = text.replace(marker, marker + '\n        routeSummary = "Прямых IP-маршрутов: \\(ipv4.excludedRoutes?.count ?? 0)"', 1)

    # Custom builder revisions may append the route array to the diagnostic
    # String. Keep the routes themselves; remove only the invalid String sum.
    text = re.sub(
        r'(?m)^([ \t]*routeSummary[ \t]*=[ \t]*"[^"\n]*")[ \t]*\+[ \t]*directRoutes\b',
        r'\1', text,
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
    text, signature_count = re.subn(
        r'func start\(transport: String, url: String, maxToken: String, maxUid: String\)',
        'func start(transport: String, url: String, maxToken: String, maxUid: String, igorDirectDomainsText: String)',
        text,
    )
    if signature_count == 0:
        # Migrate repositories already modified by an earlier revision.
        text, signature_count = re.subn(
            r'func start\(transport: String, url: String, maxToken: String, maxUid: String, directDomains: String\)',
            'func start(transport: String, url: String, maxToken: String, maxUid: String, igorDirectDomainsText: String)',
            text,
        )
    if signature_count != 1 and 'igorDirectDomainsText: String)' not in text:
        fail("Не найдена сигнатура VPNController.start для прямых сайтов")
    config_count = 0
    if '"igorDirectDomainsText": igorDirectDomainsText' not in text:
        text, config_count = re.subn(
            r'("maxToken": maxToken, "maxUid": maxUid,)',
            r'\1\n                "igorDirectDomainsText": igorDirectDomainsText,', text, count=1,
        )
    if config_count != 1 and '"igorDirectDomainsText": igorDirectDomainsText' not in text:
        fail("Не найдена конфигурация VPNController для прямых сайтов")
    # The previous patch revision used the same key as the builder's own
    # [String] setting. Remove only that exact injected String entry.
    text = re.sub(r'^[ \t]*"directDomains": directDomains,\n', '', text, flags=re.M)
    # Signing workflows may change the app identifier. Match the embedded
    # extension and never reuse some other VPN profile from iOS preferences.
    text = re.sub(r'private let extensionBundleId\s*=\s*"[^"]+"',
                  'private let extensionBundleId = (Bundle.main.bundleIdentifier ?? "") + ".tunnel"',
                  text)
    if 'manager = managers.first {' not in text:
        text = text.replace('manager = managers.first',
                            'manager = managers.first { ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == extensionBundleId }')
    text = text.replace('m.localizedDescription = "OpenFlux"',
                        'm.localizedDescription = "Igor VPN"')
    # Let iOS reconnect the packet tunnel even while the app is suspended.
    if 'm.onDemandRules = [NEOnDemandRuleConnect()]' not in text:
        text, count = re.subn(
            r'(?m)^([ \t]*)m\.isEnabled = true$',
            r'\1m.onDemandRules = [NEOnDemandRuleConnect()]\n\1m.isOnDemandEnabled = true\n\1m.isEnabled = true',
            text, count=1,
        )
        if count != 1:
            fail("Не найдена настройка VPN для автоматического переподключения")
    # On-demand may already have started the tunnel after saving the profile.
    if 'if m.connection.status == .disconnected {' not in text:
        text = text.replace('try m.connection.startVPNTunnel()',
                            'if m.connection.status == .disconnected {\n                    try m.connection.startVPNTunnel()\n                }', 1)
    # A manual Stop must disable on-demand before stopping the connection.
    old_stop = '''func stop() {
        manager?.connection.stopVPNTunnel()
    }'''
    new_stop = '''func stop() {
        Task {
            guard let m = manager else { return }
            m.isOnDemandEnabled = false
            do {
                try await m.saveToPreferences()
                try await m.loadFromPreferences()
                m.connection.stopVPNTunnel()
                refreshStatus()
            } catch {
                status = "Error: \\(error.localizedDescription)"
            }
        }
    }'''
    if old_stop in text:
        text = text.replace(old_stop, new_stop, 1)
    elif 'm.isOnDemandEnabled = false' not in text:
        fail("Не найден VPNController.stop для ручного отключения")
    if 'func refreshLog()' not in text:
        text, count = re.subn(
            r'@Published\s+var\s+status\s*:\s*String\s*=\s*"Disconnected"',
            lambda _m: '''@Published var status: String = "Disconnected" {
        didSet {
            if status != oldValue { appendDiagnostic("Статус: \\(status)") }
        }
    }''', text, count=1,
        )
        if count != 1:
            fail("Не найден статус в VPNController.swift для журнала")
        marker = 'private var manager: NETunnelProviderManager?'
        if marker not in text:
            fail("Не найден VPN manager для чтения логов расширения")
        diagnostics = r'''
    @Published private(set) var log = UserDefaults.standard.string(forKey: "igorVPNLog") ?? ""

    private func appendDiagnostic(_ message: String) {
        let stamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        log += "\n[\(stamp)] \(message)"
        if log.count > 16000 { log = String(log.suffix(16000)) }
        UserDefaults.standard.set(log, forKey: "igorVPNLog")
    }

    func refreshLog() {
        guard let session = manager?.connection as? NETunnelProviderSession,
              session.status == .connected else { return }
        do {
            try session.sendProviderMessage(Data("logs".utf8)) { [weak self] data in
                guard let data = data, let entry = String(data: data, encoding: .utf8),
                      !entry.isEmpty else { return }
                Task { @MainActor [weak self] in self?.appendDiagnostic(entry) }
            }
        } catch {
            appendDiagnostic("Ошибка чтения логов: \(error.localizedDescription)")
        }
    }
'''
        text = text.replace(marker, marker + diagnostics, 1)
    path.write_text(text, encoding="utf-8")
    print("OK Mail.ru in VPNController:", path)


def patch_tunnel_controller(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if 'case mailru = "mailru"' not in text:
        text, count = re.subn(r'(case yandex\s*=\s*"yandex")',
                              r'\1\n    case mailru = "mailru"', text, count=1)
        if count != 1:
            fail("Не найден enum TransportKind в TunnelController.swift")
    if 'case .mailru: return "Mail.ru Docs"' not in text:
        text, count = re.subn(r'(case \.yandex:\s*return "Yandex Docs")',
                              r'\1\n        case .mailru: return "Mail.ru Docs"', text, count=1)
        if count != 1:
            fail("Не найден title транспорта в TunnelController.swift")
    path.write_text(text, encoding="utf-8")
    print("OK Mail.ru enum:", path)


def patch_go_ios_bridge(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if '"openflux/transport/mailru"' not in text:
        text, count = re.subn(r'("openflux/transport"\s*\n)',
                              r'\1\t"openflux/transport/mailru"\n', text, count=1)
        if count != 1:
            fail(f"Не найден импорт transport в {path}")
    if 'case "mailru":' not in text:
        text, count = re.subn(
            r'(case "yandex", "":\s*\n\s*t = transport.NewCompressedTransport\(yandex.NewYandexDocsTransport\(docURL, config\)\))',
            r'\1\n\tcase "mailru":\n\t\tt = transport.NewCompressedTransport(mailru.NewMailruDocsTransport(docURL, config))',
            text, count=1,
        )
        if count != 1:
            fail(f"Не найден switch yandex в {path}")
    path.write_text(text, encoding="utf-8")
    print("OK Mail.ru Go bridge:", path)


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

    patch_tunnel_controller(root / "ios-app/OpenFlux/TunnelController.swift")
    patch_go_ios_bridge(root / "export_ios.go")
    patch_go_ios_bridge(root / "export_ios_packet.go")
    patch_content_view(root / "ios-app/OpenFlux/ContentView.swift")
    create_support_view(root / "ios-app/OpenFlux")
    create_direct_domains_editor(root / "ios-app/OpenFlux")
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
    print("- Start запускает системный VPN, Stop останавливает его")
    print("- список прямых сайтов открывается существующей верхней кнопкой")
    print("- Поддержать: номер 89126438781, ОТП Банк, без QR")
    print("- app-icon.png применяется автоматически")


if __name__ == "__main__":
    main()
