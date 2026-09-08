import SwiftUI

@main
struct LockoutApp: App {

    @StateObject private var sessions = SessionStore.shared
    @StateObject private var shield = ShieldController.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .task {
                    // Tidy up what the extensions couldn't afford to do themselves.
                    Judgements.drainSpool()
                    Judgements.trim()
                    reconcile()
                }
        }
    }

    /// Make the shield agree with the session on launch.
    ///
    /// Two things can drift while the app isn't running, and both are worth fixing at startup
    /// rather than leaving for someone to notice:
    ///
    /// - A session ended (its schedule fired, or it expired) but the shield is somehow still up.
    ///   That is the failure that would get the app deleted, so it is corrected unconditionally.
    /// - A session is live but the shield isn't applied — an app reinstall, a Screen Time
    ///   re-authorization, a token that stopped resolving. Re-applying is right: the user asked
    ///   for those apps to be shut and they haven't said otherwise.
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
