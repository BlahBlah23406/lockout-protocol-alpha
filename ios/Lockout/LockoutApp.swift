import SwiftUI

@main
struct LockoutApp: App {

    @StateObject private var sessions = SessionStore.shared
    @StateObject private var shield = ShieldController.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .task {
                    // What the extensions couldn't afford to do themselves.
                    Judgements.drainSpool()
                    Judgements.trim()
                    reconcile()
                }
        }
    }

    /// Make the shield agree with the session on launch.
    ///
    /// A shield still up after its session ended is the failure that gets the app deleted; a
    /// session live with no shield applied means a reinstall or a re-authorization dropped it.
    /// Both are corrected here.
    @MainActor
    private func reconcile() {
        if let session = sessions.current {
            if !shield.isShielding {
                shield.apply(tokens: session.shieldedTokens)
                shield.schedule(until: session.endsAt)
            }
        } else if shield.isShielding {
            shield.clear()
            shield.stopSchedule()
        }
    }
}
