import XCTest
@testable import Guardian

/// Unit tests for the pure logic ported from the Android app (FrameQuality + Ollama parsing).
final class GuardianTests: XCTestCase {

    // MARK: - FrameQuality

    func testAllBlackIsUnreadable() {
        let lums = [Int](repeating: 0, count: 1024)
        XCTAssertTrue(FrameQuality.isUnreadableLuminance(lums))
    }

    func testUniformGrayIsUnreadable() {
        // No variance -> nothing to see.
        let lums = [Int](repeating: 128, count: 1024)
        XCTAssertTrue(FrameQuality.isUnreadableLuminance(lums))
    }

    func testEmptyIsUnreadable() {
        XCTAssertTrue(FrameQuality.isUnreadableLuminance([]))
    }

    func testHighVarianceIsReadable() {
        // Alternating dark/bright -> real content.
        let lums = (0..<1024).map { $0 % 2 == 0 ? 10 : 240 }
        XCTAssertFalse(FrameQuality.isUnreadableLuminance(lums))
    }

    func testMostlyBlackWithSomeContentIsReadable() {
        var lums = [Int](repeating: 0, count: 1000)
        for i in 0..<100 { lums[i] = 200 }   // 10% bright -> variance well above threshold
        XCTAssertFalse(FrameQuality.isUnreadableLuminance(lums))
    }

    // MARK: - Ollama verdict parsing

    func testParseViolationTrue() {
        let body = #"{"message":{"content":"{\"violation\": true, \"reason\": \"explicit image\"}"}}"#
        let v = OllamaClient.parseVerdict(body)
        XCTAssertTrue(v.violation)
        XCTAssertEqual(v.reason, "explicit image")
        XCTAssertFalse(v.undetermined)
    }

    func testParseViolationFalse() {
        let body = #"{"message":{"content":"{\"violation\": false}"}}"#
        let v = OllamaClient.parseVerdict(body)
        XCTAssertFalse(v.violation)
        XCTAssertFalse(v.undetermined)
    }

    func testParseGarbageIsUndetermined() {
        let v = OllamaClient.parseVerdict("not json at all")
        XCTAssertTrue(v.undetermined)
        XCTAssertFalse(v.violation)
    }

    func testParseMissingContentIsUndetermined() {
        let v = OllamaClient.parseVerdict(#"{"message":{}}"#)
        XCTAssertTrue(v.undetermined)
    }

    // MARK: - Emulated devices

    /// Discovery must actually find the emulators on this Mac — the catalog is worthless if the
    /// scan can't see them. Simulator lives inside Xcode.app and PlayCover's apps live in a
    /// container, so both are easy to miss.
    @MainActor
    func testDiscoveryFindsInstalledEmulators() {
        let ids = Emulators.installedIds()
        XCTAssertFalse(ids.isEmpty, "no emulated devices discovered at all — scan is broken")
        for id in ids { XCTAssertTrue(Emulators.isEmulator(id)) }
        // Xcode's Simulator is nested inside Xcode.app; if Xcode is installed it must be found.
        if FileManager.default.fileExists(atPath: "/Applications/Xcode.app") {
            XCTAssertTrue(ids.contains("com.apple.iphonesimulator"),
                          "Xcode is installed but its Simulator wasn't discovered")
        }
    }

    /// Bundle-less emulators (the Android SDK `emulator` binary) get a synthetic `proc:` id, and
    /// hide/quit must still be able to resolve it.
    func testProcessIdsArePrefixed() {
        for id in Emulators.processIds {
            XCTAssertTrue(id.hasPrefix(FrontmostApp.procPrefix))
            XCTAssertFalse(FrontmostApp.shortName(for: id).contains(FrontmostApp.procPrefix))
        }
        XCTAssertTrue(Emulators.processIds.contains("proc:qemu-system-aarch64"))
    }

    /// A dotted app name must survive the installed-apps scan (regression: "com.ninjakiwi.
    /// bloonstd6.app" was being displayed as "com.ninjakiwi").
    func testDottedAppNamesArentTruncated() {
        for app in InstalledApps.all() {
            XCTAssertFalse(app.name.hasSuffix(".app"))
        }
    }
}
