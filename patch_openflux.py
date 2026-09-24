#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "OpenFlux")
IOS = ROOT / "ios-app"
CONTENT = IOS / "OpenFlux" / "ContentView.swift"
VPN = IOS / "OpenFlux" / "VPNController.swift"
TUNNEL = IOS / "OpenFluxTunnel" / "PacketTunnelProvider.swift"
EDITOR = IOS / "OpenFlux" / "DirectDomainsEditor.swift"

for p in (CONTENT, VPN, TUNNEL):
    if not p.exists():
        raise SystemExit(f"Required upstream file not found: {p}")


def find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    i = open_index
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
                block_comment += 1; i += 2; continue
            if ch == "*" and nxt == "/":
                block_comment -= 1; i += 2; continue
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
            line_comment = True; i += 2; continue
        if ch == "/" and nxt == "*":
            block_comment = 1; i += 2; continue
        if ch == '"':
            in_string = True; i += 1; continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("Unmatched brace")


# 1) Add the in-app Direct Domains editor.
EDITOR.write_text(r'''import SwiftUI

struct DirectDomainsEditor: View {
    @Binding var text: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationView {
            Form {
                Section("Напрямую без VPN") {
                    TextEditor(text: $text)
                        .font(.system(.body, design: .monospaced))
                        .frame(minHeight: 220)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    Text("Один домен или IPv4-адрес на строку. Всё, чего нет в списке, идёт через OpenFlux. Изменения применяются после переподключения VPN. Для поддоменов указывай их отдельными строками.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("Пример") {
                    Text("vk.com\napi.vk.com\nyandex.ru\nmax.ru")
                        .font(.system(.footnote, design: .monospaced))
                        .textSelection(.enabled)
                }
            }
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

ct = CONTENT.read_text(encoding="utf-8")
if "OPENFLUX_CUSTOM_DIRECT_DOMAINS" not in ct:
    marker = re.search(r"struct\s+ContentView\s*:\s*View\s*\{", ct)
    if not marker:
        raise SystemExit("Could not find ContentView declaration")
    insert_at = marker.end()
    props = r'''
    // OPENFLUX_CUSTOM_DIRECT_DOMAINS
    @AppStorage("directDomains") private var directDomains: String = ""
    @State private var showDirectDomainsEditor = false
'''
    ct = ct[:insert_at] + props + ct[insert_at:]

    body = re.search(r"\bvar\s+body\s*:\s*some\s+View\s*\{", ct)
    if not body:
        raise SystemExit("Could not find ContentView.body")
    open_brace = ct.find("{", body.start())
    close_brace = find_matching_brace(ct, open_brace)
    original = ct[open_brace + 1:close_brace]
    wrapped = r'''
        ZStack(alignment: .topTrailing) {
            Group {
''' + original + r'''
            }

            Button {
                showDirectDomainsEditor = true
            } label: {
                Image(systemName: "arrow.triangle.branch")
                    .font(.system(size: 17, weight: .semibold))
                    .padding(11)
                    .background(.ultraThinMaterial, in: Circle())
            }
            .accessibilityLabel("Прямые сайты")
            .padding(.top, 8)
            .padding(.trailing, 10)
        }
        .sheet(isPresented: $showDirectDomainsEditor) {
            DirectDomainsEditor(text: $directDomains)
        }
'''
    ct = ct[:open_brace + 1] + wrapped + ct[close_brace:]
    CONTENT.write_text(ct, encoding="utf-8")


# 2) Pass the editable list into NETunnelProviderProtocol.providerConfiguration.
vc = VPN.read_text(encoding="utf-8")
if "OPENFLUX_CUSTOM_DIRECT_DOMAINS" not in vc:
    class_match = re.search(r"(?:final\s+)?class\s+VPNController[^\{]*\{", vc)
    if not class_match:
        raise SystemExit("Could not find VPNController class")
    helper = r'''
    // OPENFLUX_CUSTOM_DIRECT_DOMAINS
    private static func directDomainsFromDefaults() -> [String] {
        let raw = UserDefaults.standard.string(forKey: "directDomains") ?? ""
        let separators = CharacterSet(charactersIn: "\n,;")
        return raw.components(separatedBy: separators)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
            .map { value -> String in
                var v = value
                if v.hasPrefix("*.") { v.removeFirst(2) }
                if v.contains("://"), let host = URL(string: v)?.host { return host.lowercased() }
                if let slash = v.firstIndex(of: "/") { v = String(v[..<slash]) }
                if let colon = v.firstIndex(of: ":"), !v.contains(":") || v.filter({ $0 == ":" }).count == 1 {
                    v = String(v[..<colon])
                }
                return v.trimmingCharacters(in: CharacterSet(charactersIn: "."))
            }
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }
            .reduce(into: [String]()) { out, value in
                if !out.contains(value) { out.append(value) }
            }
    }
'''
    vc = vc[:class_match.end()] + helper + vc[class_match.end():]

    pconf = re.search(r"proto\.providerConfiguration\s*=\s*\[", vc)
    if not pconf:
        raise SystemExit("Could not find proto.providerConfiguration dictionary")
    bracket = vc.find("[", pconf.start())
    vc = vc[:bracket + 1] + '\n            "directDomains": Self.directDomainsFromDefaults(),' + vc[bracket + 1:]
    VPN.write_text(vc, encoding="utf-8")


# 3) Resolve exact direct domains before enabling the tunnel and add /32 excluded routes.
pt = TUNNEL.read_text(encoding="utf-8")
if "OPENFLUX_CUSTOM_DIRECT_DOMAINS" not in pt:
    if "import Foundation" not in pt:
        pt = pt.replace("import NetworkExtension", "import NetworkExtension\nimport Foundation", 1)
    if "import Darwin" not in pt:
        if "import Foundation" in pt:
            pt = pt.replace("import Foundation", "import Foundation\nimport Darwin", 1)
        else:
            pt = "import Darwin\n" + pt

    class_match = re.search(r"(?:final\s+)?class\s+PacketTunnelProvider[^\{]*\{", pt)
    if not class_match:
        raise SystemExit("Could not find PacketTunnelProvider class")
    helper = r'''
    // OPENFLUX_CUSTOM_DIRECT_DOMAINS
    private static func resolveIPv4(_ host: String) -> [String] {
        if host.range(of: #"^\d{1,3}(?:\.\d{1,3}){3}$"#, options: .regularExpression) != nil {
            return [host]
        }

        var hints = addrinfo()
        hints.ai_flags = AI_ADDRCONFIG
        hints.ai_family = AF_INET
        hints.ai_socktype = SOCK_STREAM
        hints.ai_protocol = IPPROTO_TCP

        var result: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, nil, &hints, &result) == 0 else { return [] }
        defer { if let result { freeaddrinfo(result) } }

        var addresses = Set<String>()
        var cursor = result
        while let current = cursor {
            let info = current.pointee
            if info.ai_family == AF_INET, let rawAddress = info.ai_addr {
                var socketAddress = rawAddress.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
                    $0.pointee
                }
                var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                let converted = buffer.withUnsafeMutableBufferPointer { ptr in
                    inet_ntop(AF_INET, &socketAddress.sin_addr, ptr.baseAddress, socklen_t(INET_ADDRSTRLEN))
                }
                if converted != nil {
                    addresses.insert(String(cString: buffer))
                }
            }
            cursor = info.ai_next
        }
        return Array(addresses)
    }

    private static func makeDirectRoutes(from hosts: [String]) -> [NEIPv4Route] {
        var seen = Set<String>()
        var routes: [NEIPv4Route] = []
        for host in hosts {
            for address in resolveIPv4(host) where seen.insert(address).inserted {
                routes.append(NEIPv4Route(destinationAddress: address,
                                          subnetMask: "255.255.255.255"))
            }
        }
        return routes
    }
'''
    pt = pt[:class_match.end()] + helper + pt[class_match.end():]

    # Upstream currently reads config into `conf`; insert after maxUid when possible.
    maxuid = re.search(r"^\s*let\s+maxUid\s*=.*$", pt, flags=re.MULTILINE)
    if maxuid:
        pos = maxuid.end()
        injection = r'''
        let directDomains = (conf["directDomains"] as? [String]) ?? []
        let directRoutes = Self.makeDirectRoutes(from: directDomains)
'''
        pt = pt[:pos] + injection + pt[pos:]
    else:
        # Fallback: insert before IPv4 settings, assuming upstream keeps `conf`.
        settings = re.search(r"^\s*let\s+ipv4\s*=\s*NEIPv4Settings", pt, flags=re.MULTILINE)
        if not settings:
            raise SystemExit("Could not locate maxUid or IPv4 settings in PacketTunnelProvider")
        injection = r'''        let directDomains = (conf["directDomains"] as? [String]) ?? []
        let directRoutes = Self.makeDirectRoutes(from: directDomains)

'''
        pt = pt[:settings.start()] + injection + pt[settings.start():]

    new_pt, count = re.subn(
        r"ipv4\.excludedRoutes\s*=\s*Self\.bypassRoutes",
        "ipv4.excludedRoutes = Self.bypassRoutes + directRoutes",
        pt,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not patch ipv4.excludedRoutes")
    pt = new_pt
    TUNNEL.write_text(pt, encoding="utf-8")

print("OpenFlux custom direct-domain patch applied successfully.")
