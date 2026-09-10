import CryptoKit
import Foundation
import Security

/// Keychain wrapper for the things that must not sit in a shared defaults plist: API keys, the
/// passcode hash, and the ntfy topic. The access group lets the shield action extension read the
/// topic when it needs to alert a partner.
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
        // Delete-then-add: an update on a missing item fails, and branching is more code.
        delete(key)
        guard !value.isEmpty else { return }
        var attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: Data(value.utf8),
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
