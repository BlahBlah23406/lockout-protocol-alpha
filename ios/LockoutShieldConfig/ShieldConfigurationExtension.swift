import ManagedSettings
import ManagedSettingsUI
import SwiftUI
import UIKit

/// What the shield looks like when you open a shielded app.
///
/// Runs in its own process with a few megabytes to spend: no networking, no session mutation, no
/// shared singletons. It reads the session file, formats two strings, and returns.
///
/// It is the only place the user meets the product mid-session, so it quotes their own words back
/// at them rather than saying "blocked".
class ShieldConfigurationExtension: ShieldConfigurationDataSource {

    override func configuration(shielding application: Application) -> ShieldConfiguration {
        build(appName: application.localizedDisplayName)
    }

    override func configuration(shielding application: Application,
                                in category: ActivityCategory) -> ShieldConfiguration {
        build(appName: application.localizedDisplayName)
    }

    override func configuration(shielding webDomain: WebDomain) -> ShieldConfiguration {
        build(appName: webDomain.domain)
    }

    override func configuration(shielding webDomain: WebDomain,
                                in category: ActivityCategory) -> ShieldConfiguration {
        build(appName: webDomain.domain)
    }

    // MARK: - The screen

    private func build(appName: String?) -> ShieldConfiguration {
        let session = SharedSession.current()
        let locked = session?.accountability == .locked
        let name = appName ?? "This app"

        let title: String
        let subtitle: String

        if let session {
            title = "You said you were:"
            subtitle = shieldBody(task: session.task, appName: name, locked: locked)
        } else {
            // The session ended but iOS hasn't lifted the shield yet — a reachable state.
            title = "Session over"
            subtitle = "This shield is being lifted. Open Lockout if it's still here in a minute."
        }

        return ShieldConfiguration(
            backgroundBlurStyle: .systemUltraThinMaterialDark,
            backgroundColor: UIColor(red: 0.02, green: 0.03, blue: 0.05, alpha: 1),
            icon: nil,
            title: ShieldConfiguration.Label(text: title, color: .init(white: 0.8, alpha: 1)),
            subtitle: ShieldConfiguration.Label(text: subtitle, color: gold),
            primaryButtonLabel: ShieldConfiguration.Label(
                text: "Back to work", color: .black),
            primaryButtonBackgroundColor: orange,
            secondaryButtonLabel: ShieldConfiguration.Label(
                text: locked ? "Unshield (passcode)" : "I'm on task",
                color: .init(white: 0.9, alpha: 1)))
    }

    private func shieldBody(task: String, appName: String, locked: Bool) -> String {
        let tail = locked
            ? "This session is locked — unshielding needs your passcode, and your accountability "
            + "partner is told either way."
            : "This session is self-managed. Unshielding is logged and counted in your summary."
        return "\(task)\n\n\(appName) isn't part of that.\n\n\(tail)"
    }

    // Inlined: an extension shouldn't spend its memory budget reading an asset catalog.
    private var gold: UIColor { UIColor(red: 1.0, green: 0.8, blue: 0.4, alpha: 1) }
    private var orange: UIColor { UIColor(red: 1.0, green: 0.6, blue: 0.4, alpha: 1) }
}
