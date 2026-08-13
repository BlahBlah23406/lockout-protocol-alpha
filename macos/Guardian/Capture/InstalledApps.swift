import AppKit
import Foundation

/// Enumerates ALL installed applications (not just the running ones) by scanning the standard
/// macOS application directories. Used by the app pickers so you can choose any app to monitor,
/// even one that isn't open right now.
enum InstalledApps {

    struct App: Identifiable, Hashable {
        let id: String      // bundle identifier
        let name: String
        let url: URL
    }

    /// Cached so repeated picker opens don't re-scan the disk every time.
    private static var cache: [App]?

    static func all(refresh: Bool = false) -> [App] {
        if !refresh, let cache { return cache }

        let fm = FileManager.default
        var dirs: [URL] = [
            URL(fileURLWithPath: "/Applications"),
            URL(fileURLWithPath: "/Applications/Utilities"),
            URL(fileURLWithPath: "/System/Applications"),
            URL(fileURLWithPath: "/System/Applications/Utilities"),
            // Xcode ships the iOS/watchOS/visionOS Simulator inside its own bundle, so it never
            // shows up in a plain /Applications scan — and an emulated device is exactly what we
            // must not miss. See Emulators.swift.
            URL(fileURLWithPath: "/Applications/Xcode.app/Contents/Developer/Applications"),
            URL(fileURLWithPath: "/Applications/Xcode-beta.app/Contents/Developer/Applications"),
        ]
        if let home = fm.homeDirectoryForCurrentUser as URL? {
            dirs.append(home.appendingPathComponent("Applications"))
            // PlayCover's wrapped iOS apps: the shortcut folder, and the container they really
            // live in (the shortcuts go stale when a wrapped app is removed).
            dirs.append(home.appendingPathComponent("Applications/PlayCover"))
            dirs.append(home.appendingPathComponent(
                "Library/Containers/io.playcover.PlayCover/Applications"))
        }

        var byId: [String: App] = [:]
        for dir in dirs {
            guard let items = try? fm.contentsOfDirectory(
                at: dir, includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]) else { continue }
            for url in items where url.pathExtension == "app" {
                guard let id = bundleId(at: url), byId[id] == nil else { continue }
                // Strip only the ".app" suffix — `deletingPathExtension` would turn a dotted name
                // like "com.ninjakiwi.bloonstd6.app" into "com.ninjakiwi".
                var name = fm.displayName(atPath: url.path)
                if name.hasSuffix(".app") { name.removeLast(4) }
                byId[id] = App(id: id, name: name, url: url)
            }
        }

        // Emulators that are bare executables with no bundle at all (the Android SDK emulator).
        // They get a synthetic `proc:` id so they can be listed, monitored, and blocked like
        // anything else.
        for id in Emulators.installedProcessIds() where byId[id] == nil {
            let exe = id.replacingOccurrences(of: FrontmostApp.procPrefix, with: "")
            byId[id] = App(id: id, name: exe, url: URL(fileURLWithPath: "/"))
        }

        let list = byId.values.sorted {
            $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }
        cache = list
        return list
    }

    /// Bundle identifier of an app bundle on disk. Handles both macOS bundles
    /// (`Contents/Info.plist`) and the iOS-style flat bundles PlayCover produces (`Info.plist` at
    /// the root), which `Bundle(url:)` alone doesn't read reliably.
    static func bundleId(at url: URL) -> String? {
        if let bundle = Bundle(url: url), let id = bundle.bundleIdentifier { return id }
        for plist in ["Contents/Info.plist", "Info.plist", "Wrapper/Info.plist"] {
            let path = url.appendingPathComponent(plist)
            if let dict = NSDictionary(contentsOf: path),
               let id = dict["CFBundleIdentifier"] as? String, !id.isEmpty {
                return id
            }
        }
        return nil
    }

    /// Best-effort display name for a bundle id, falling back to a running app or the last
    /// dotted component.
    static func name(for bundleId: String) -> String {
        if let app = all().first(where: { $0.id == bundleId }) { return app.name }
        return FrontmostApp.shortName(for: bundleId)
    }
}
