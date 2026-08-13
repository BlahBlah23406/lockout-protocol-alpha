import AppKit
import Foundation

/// Emulators, simulators, virtual machines and phone-mirroring apps — every way this Mac can put
/// ANOTHER device's screen inside a window here.
///
/// These are a monitoring blind spot by nature: to Guardian an emulator is just one more Mac app,
/// but what's inside its window is a whole other device with its own browser and its own app store,
/// none of which the Mac's other content blockers touch. So every one of them belongs on the
/// monitored list. (The screenshot is of the whole display, so an emulator's window is captured and
/// classified exactly like any other app's — no special capture path is needed.)
///
/// `syncMonitoredApps()` folds the installed ones into `Prefs.monitoredApps` at every launch, so an
/// emulator installed tomorrow is watched the first time it runs, not whenever the list is next
/// edited by hand.
enum Emulators {

    /// Known bundle identifiers, by family. Listed whether or not they're installed today — the
    /// catalog is what makes a future install get picked up automatically.
    ///
    /// Anything running a guest OS or a guest device counts. Remote-desktop / cloud-streaming
    /// clients (TeamViewer, Chrome Remote Desktop, Shadow, GeForce NOW) are deliberately NOT here:
    /// they show a machine that is somewhere else, which is a different question from a device
    /// emulated on this Mac. iPhone Mirroring IS here — it puts a real phone's screen on this
    /// display, which is the same blind spot in practice.
    static let catalog: Set<String> = [
        // ── Mobile-device emulators / simulators
        "com.apple.iphonesimulator",        // Xcode Simulator (iOS / watchOS / tvOS / visionOS)
        "com.apple.ScreenContinuity",       // iPhone Mirroring — a real phone's screen, on this Mac
        "com.now.gg.BlueStacks",            // BlueStacks (Android)
        "com.now.gg.BlueStacksMIM",         // BlueStacks multi-instance manager
        "com.bluestacks.AppPlayer",         // older BlueStacks builds
        "com.genymobile.genymotion",        // Genymotion (Android)
        "com.google.android.studio",        // Android Studio — hosts the AVD emulator window
        "com.google.android.studio-EAP",
        "io.playcover.PlayCover",           // PlayCover — runs iOS apps on Apple silicon
        "com.nox.noxplayer",                // Nox (Android)
        "com.MEmu.MEmuPlay",                // MEmu (Android)
        "com.corellium.Corellium",          // Corellium virtual devices

        // ── Virtual machines (a guest OS is a guest browser)
        "com.utmapp.UTM",
        "com.utmapp.UTM-SE",
        "com.parallels.desktop.console",
        "com.vmware.fusion",
        "org.virtualbox.app.VirtualBox",
        "com.electric-sheep.vagrant",
        "com.getutm.UTM",
        "com.veertu.anka",
        "com.kandji.veertu",
        "org.qemu.qemu",
        "com.lima-vm.lima",
        "io.orbstack.OrbStack",
        "com.docker.docker",                // Docker Desktop — can host a GUI/VNC guest
        "com.vmware.horizon",

        // ── Compatibility layers (a Windows/console guest inside a Mac window)
        "com.isaacmarovitz.Whisky",         // Wine
        "com.paulthetall.portingkit",       // Wine wrapper
        "com.codeweavers.CrossOver",
        "org.winehq.wine",

        // ── Console emulators (still a second screen with a browser in some cases)
        "org.ryujinx.Ryujinx",
        "com.citra-emu.citra",
        "org.dolphin-emu.dolphin",
        "org.ppsspp.ppsspp",
        "net.pcsx2.pcsx2",
        "org.rpcs3.rpcs3",
        "com.libretro.RetroArch",
        "org.openemu.OpenEmu",
    ]

    /// Bundle-less emulator binaries, keyed by executable name. The Android SDK emulator is a bare
    /// Mach-O (`emulator` / `qemu-system-*`) with NO bundle identifier, so `NSWorkspace` reports
    /// nothing for it and it would otherwise be invisible to the monitor. `FrontmostApp` gives such
    /// processes the synthetic id `proc:<executable>` — these are those ids.
    /// See `FrontmostApp.procPrefix`.
    static let processNames: Set<String> = [
        "emulator",
        "qemu-system-aarch64",
        "qemu-system-x86_64",
        "qemu-system-arm",
        "qemu-system-armel",
        "qemu-system-i386",
    ]

    /// Synthetic ids for the bundle-less binaries above.
    static var processIds: Set<String> {
        Set(processNames.map { FrontmostApp.procPrefix + $0 })
    }

    /// Every id we consider an emulated device: the catalog, the bundle-less binaries, and any
    /// PlayCover-wrapped iOS app found on disk (each of those is its own iOS bundle id).
    static func allIds() -> Set<String> {
        catalog.union(processIds).union(playCoverIds())
    }

    /// Is this app one of the emulated-device family? Used to tag it in the picker so unticking one
    /// is at least a deliberate, informed act.
    static func isEmulator(_ bundleId: String) -> Bool {
        allIds().contains(bundleId)
    }

    // MARK: - Discovery

    /// The subset of `allIds()` actually present on this Mac right now. Installed apps come from
    /// `InstalledApps` (which scans nested locations like Xcode's Simulator.app and the PlayCover
    /// folder); bundle-less emulators are looked up on disk by path.
    static func installedIds() -> Set<String> {
        var found = Set(InstalledApps.all().map(\.id)).intersection(catalog)
        // These two are discovered by looking on disk, so finding one IS the installed check.
        found.formUnion(playCoverIds())
        found.formUnion(installedProcessIds())
        return found
    }

    /// PlayCover-wrapped iOS apps. These are real iOS apps running on the Mac, each with its own iOS
    /// bundle id, so they can't be listed in the catalog ahead of time.
    ///
    /// Two locations: PlayCover's container (where the wrapped app actually lives) and
    /// `~/Applications/PlayCover` (shortcuts into it). The shortcut folder is checked too but is not
    /// trusted on its own — its entries are symlinks that go stale when an app is removed.
    static func playCoverIds() -> Set<String> {
        let fm = FileManager.default
        let home = fm.homeDirectoryForCurrentUser
        let dirs = [
            home.appendingPathComponent(
                "Library/Containers/io.playcover.PlayCover/Applications"),
            home.appendingPathComponent("Applications/PlayCover"),
        ]
        var ids = Set<String>()
        for dir in dirs {
            guard let items = try? fm.contentsOfDirectory(
                at: dir, includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]) else { continue }
            ids.formUnion(items.filter { $0.pathExtension == "app" }
                               .compactMap { InstalledApps.bundleId(at: $0) })
        }
        return ids
    }

    /// Bundle-less emulator binaries present on disk, as `proc:` ids. Covers the Android SDK
    /// emulator in its standard locations plus a Homebrew-installed qemu.
    static func installedProcessIds() -> Set<String> {
        let fm = FileManager.default
        let home = fm.homeDirectoryForCurrentUser
        let dirs = [
            home.appendingPathComponent("Library/Android/sdk/emulator"),
            home.appendingPathComponent("Library/Android/sdk/emulator/qemu/darwin-aarch64"),
            home.appendingPathComponent("Library/Android/sdk/emulator/qemu/darwin-x86_64"),
            URL(fileURLWithPath: "/opt/homebrew/bin"),
            URL(fileURLWithPath: "/usr/local/bin"),
        ]
        var ids = Set<String>()
        for dir in dirs {
            for name in processNames
            where fm.isExecutableFile(atPath: dir.appendingPathComponent(name).path) {
                ids.insert(FrontmostApp.procPrefix + name)
            }
        }
        return ids
    }

    // MARK: - Sync

    /// Add every installed emulated device to the monitored list. Runs at launch, so a newly
    /// installed emulator is covered without anyone remembering to tick a box. Returns the ids it
    /// added (empty when there was nothing new).
    ///
    /// This intentionally re-adds an emulator that was unticked in Settings — on an accountability
    /// app, "I quietly removed the Android emulator from the watch list" is exactly the edit that
    /// shouldn't stick silently. The additions are written to the activity log either way.
    @MainActor
    @discardableResult
    static func syncMonitoredApps() -> Set<String> {
        let prefs = Prefs.shared
        let installed = installedIds()
        let added = installed.subtracting(prefs.monitoredApps)
        guard !added.isEmpty else { return [] }

        prefs.monitoredApps.formUnion(added)
        let names = added.map { InstalledApps.name(for: $0) }.sorted().joined(separator: ", ")
        EventLog.shared.add("🖥️ emulated devices added to the watch list: \(names)")
        return added
    }
}
