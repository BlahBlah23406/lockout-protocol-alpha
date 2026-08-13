import Foundation

/// Tracks apps the user has temporarily "overridden" by dismissing a block screen with the PIN.
/// While an override is active, the monitor leaves that app alone — so you aren't re-blocked the
/// instant you dismiss. Mirrors the Android `Overrides`.
@MainActor
enum Overrides {
    private static var until: [String: Date] = [:]

    /// Grant an override for an app (default 5 minutes), e.g. after a correct PIN dismissal.
    static func grant(_ bundleId: String, seconds: TimeInterval = 300) {
        until[bundleId] = Date().addingTimeInterval(seconds)
    }

    static func isActive(_ bundleId: String) -> Bool {
        guard let d = until[bundleId] else { return false }
        if d > Date() { return true }
        until[bundleId] = nil
        return false
    }

    static func clear(_ bundleId: String) { until[bundleId] = nil }
}
