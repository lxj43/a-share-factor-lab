import Cocoa
import WebKit

@MainActor
final class MarketLauncher: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private let address = URL(string: "http://127.0.0.1:8769/")!
    private var server: Process?
    private var serverLog: FileHandle?
    private var ready = false
    private var quitting = false
    private var compact = false
    private var windowSize: NSRect?

    private var projectURL: URL? {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "MarketProjectPath") as? String else { return nil }
        return URL(fileURLWithPath: path, isDirectory: true)
    }

    private var logURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/FactorLab/desktop.log")
    }

    private lazy var webView: WKWebView = {
        let view = WKWebView(frame: .zero)
        view.navigationDelegate = self
        view.uiDelegate = self
        view.allowsBackForwardNavigationGestures = true
        return view
    }()

    private lazy var window: NSWindow = {
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1100, height: 800)
        let size = NSSize(width: min(1180, screen.width - 56), height: min(850, screen.height - 34))
        let host = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                            styleMask: [.titled, .closable, .miniaturizable, .resizable],
                            backing: .buffered, defer: false)
        host.title = "Factor Lab · 市场行情"
        host.contentMinSize = NSSize(width: 380, height: 380)
        host.isReleasedWhenClosed = false
        host.contentView = webView
        host.center()
        return host
    }()

    private var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMenus()
        showMessage("正在打开行情看板…")
        showWindow()
        Task { await connect() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        showWindow()
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        if server?.isRunning == true { server?.terminate() }
        try? serverLog?.close()
    }

    private func setUpLog() -> FileHandle? {
        if let serverLog { return serverLog }
        let manager = FileManager.default
        try? manager.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !manager.fileExists(atPath: logURL.path) {
            manager.createFile(atPath: logURL.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: logURL) else { return nil }
        _ = try? handle.seekToEnd()
        serverLog = handle
        return handle
    }

    private func record(_ message: String) {
        let entry = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
        if let data = entry.data(using: .utf8) { try? setUpLog()?.write(contentsOf: data) }
    }

    private func serviceIsReady() async -> Bool {
        let url = address.appendingPathComponent("api/factors")
        return await Task.detached {
            let probe = Process()
            let output = Pipe()
            probe.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
            probe.arguments = ["--noproxy", "*", "--silent", "--fail", "--max-time", "1", url.absoluteString]
            probe.standardOutput = output
            probe.standardError = FileHandle.nullDevice
            guard (try? probe.run()) != nil else { return false }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            probe.waitUntilExit()
            guard probe.terminationStatus == 0,
                  let catalog = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return false }
            return catalog["published"] is [Any] && catalog["screening"] is [Any]
        }.value
    }

    private func connect() async {
        if await serviceIsReady() {
            record("Connected to running market service")
        } else {
            do {
                try startService()
            } catch {
                record("Startup: \(error.localizedDescription)")
                showMessage("无法启动行情服务。请确认项目文件仍在原位置。")
                return
            }
            var available = false
            for _ in 0..<32 where !quitting {
                if await serviceIsReady() { available = true; break }
                if server?.isRunning != true { break }
                try? await Task.sleep(for: .milliseconds(250))
            }
            guard available && !quitting else {
                showMessage("行情服务暂未启动。请关闭应用后重开，或查看启动日志。")
                return
            }
            record("Started market service")
        }
        ready = true
        webView.load(URLRequest(url: address))
    }

    private func startService() throws {
        guard let projectURL,
              FileManager.default.fileExists(atPath: projectURL.appendingPathComponent("market_dashboard_server.py").path) else {
            throw CocoaError(.fileNoSuchFile)
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["market_dashboard_server.py"]
        process.currentDirectoryURL = projectURL
        if let handle = setUpLog() {
            process.standardOutput = handle
            process.standardError = handle
        }
        try process.run()
        server = process
    }

    private func showMessage(_ message: String) {
        webView.loadHTMLString("""
            <!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
            <style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101a16;color:#e1c28a;
            font:17px "Times New Roman","Microsoft YaHei",sans-serif;text-align:center}</style><p>\(message)</p>
            """, baseURL: nil)
    }

    @objc private func showWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func toggleCompact() {
        if compact, let previous = windowSize {
            window.level = .normal
            window.setFrame(previous, display: true, animate: true)
        } else if let screen = (window.screen ?? NSScreen.main)?.visibleFrame {
            windowSize = window.frame
            let w = min(465, screen.width - 20), h = min(690, screen.height - 26)
            window.level = .floating
            window.setFrame(NSRect(x: screen.maxX - w - 12, y: screen.maxY - h - 12, width: w, height: h),
                            display: true, animate: true)
        } else {
            return
        }
        compact.toggle()
        showWindow()
    }

    @objc private func reloadPage() {
        if ready { webView.reload() }
    }

    @objc private func showLogs() {
        NSWorkspace.shared.activateFileViewerSelecting([logURL])
    }

    @objc private func quit() { NSApp.terminate(nil) }

    private func item(_ title: String, _ action: Selector, _ key: String = "") -> NSMenuItem {
        let command = NSMenuItem(title: title, action: action, keyEquivalent: key)
        command.target = self
        return command
    }

    private func configureMenus() {
        let bar = NSMenu()
        let app = NSMenuItem()
        app.submenu = NSMenu(title: "Factor Lab")
        app.submenu?.addItem(item("打开启动日志", #selector(showLogs)))
        app.submenu?.addItem(.separator())
        app.submenu?.addItem(item("退出 Factor Lab", #selector(quit), "q"))
        bar.addItem(app)
        let edit = NSMenuItem()
        edit.submenu = NSMenu(title: "编辑")
        for (label, selector, key) in [("剪切", #selector(NSText.cut(_:)), "x"),
                                      ("复制", #selector(NSText.copy(_:)), "c"),
                                      ("粘贴", #selector(NSText.paste(_:)), "v"),
                                      ("全选", #selector(NSText.selectAll(_:)), "a")] {
            edit.submenu?.addItem(withTitle: label, action: selector, keyEquivalent: key)
        }
        bar.addItem(edit)
        let windows = NSMenuItem()
        windows.submenu = NSMenu(title: "窗口")
        windows.submenu?.addItem(item("显示窗口", #selector(showWindow), "1"))
        windows.submenu?.addItem(item("切换置顶小窗", #selector(toggleCompact), "2"))
        windows.submenu?.addItem(item("重新载入", #selector(reloadPage), "r"))
        windows.submenu?.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        bar.addItem(windows)
        NSApp.mainMenu = bar

        let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.button?.title = "Factor Lab"
        let menu = NSMenu()
        menu.addItem(item("打开行情看板", #selector(showWindow)))
        menu.addItem(item("切换置顶小窗", #selector(toggleCompact)))
        menu.addItem(.separator())
        menu.addItem(item("退出 Factor Lab", #selector(quit)))
        status.menu = menu
        statusItem = status
    }

    private func local(_ url: URL) -> Bool {
        url.scheme == address.scheme && url.host == address.host && url.port == address.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload {
            decisionHandler(.download)
        } else if let url = action.request.url, ["http", "https"].contains(url.scheme ?? ""), !local(url) {
            if action.navigationType == .linkActivated { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if local(url) { webView.load(action.request) }
            else if ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let save = NSSavePanel()
        save.nameFieldStringValue = suggestedFilename
        save.beginSheetModal(for: window) { result in completionHandler(result == .OK ? save.url : nil) }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, local(url) {
            record("Loaded \(url.path)\(url.fragment.map { "#" + $0 } ?? "")")
        }
    }
}

@main
struct MarketDesktop {
    @MainActor static func main() {
        let app = NSApplication.shared
        let launcher = MarketLauncher()
        app.setActivationPolicy(.regular)
        app.delegate = launcher
        app.run()
    }
}
