import CryptoKit
import Foundation
import Security

/// Small Keychain wrapper for the things that must not sit in a shared defaults plist: API keys,
/// the passcode hash, and the ntfy topic.
///
/// The access group is what lets the extensions read the ntfy topic (the shield action extension
/// needs it to alert a partner) while keeping everything out of the App Group's plist, which is
/// readable by anything in the group and survives in backups as plain text.
enum Keychain {

    /// Must match the `keychain-access-groups` entitlement in every target that reads a secret.
    /// The `$(AppIdentifierPrefix)` prefix is added by the build, so the literal here is the
    /// suffix only.
    private static let accessGroup = "group.com.lockoutprotocol.lockout"
    private static let service = "com.lockoutprotocol.lockout"

    static func get(_ key: String) -> String? {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        query[kSecAttrAccessGroup as String] = accessGroup

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func set(_ key: String, _ value: String) {
        // Delete-then-add rather than update: an update on a missing item fails, and branching on
        // which case we're in is more code than just replacing it.
        delete(key)
        guard !value.isEmpty else { return }
        var attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: Data(value.utf8),
            // Available after first unlock so an extension launched in the background can read it.
            // Not `WhenUnlocked`: the shield action extension can run while the phone is locked.
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        attributes[kSecAttrAccessGroup as String] = accessGroup
        SecItemAdd(attributes as CFDictionary, nil)
    }

    static func delete(_ key: String) {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        query[kSecAttrAccessGroup as String] = accessGroup
        SecItemDelete(query as CFDictionary)
    }

    static func sha256(_ s: String) -> String {
        SHA256.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
