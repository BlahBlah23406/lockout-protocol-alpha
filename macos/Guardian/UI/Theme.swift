import SwiftUI

/// LCARS (Star Trek) palette, matching the Android app's `Lcars.kt`.
enum LCARS {
    static let space   = Color(red: 0x05/255, green: 0x07/255, blue: 0x0D/255)
    static let panel   = Color(red: 0x0E/255, green: 0x12/255, blue: 0x1E/255)
    static let orange  = Color(red: 0xFF/255, green: 0x99/255, blue: 0x66/255)
    static let blue    = Color(red: 0x7F/255, green: 0xB0/255, blue: 0xFF/255)
    static let lilac   = Color(red: 0xCC/255, green: 0x88/255, blue: 0xCC/255)
    static let gold    = Color(red: 0xFF/255, green: 0xCC/255, blue: 0x66/255)
    static let red     = Color(red: 0xE0/255, green: 0x53/255, blue: 0x3D/255)
    static let readout = Color(red: 0x9A/255, green: 0xE6/255, blue: 0xC9/255) // mono panel text
}

/// LCARS "pill" button — rounded, condensed-bold, colored.
struct LcarsButton: View {
    let title: String
    var color: Color = LCARS.orange
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title.uppercased())
                .font(.system(.body, design: .rounded).weight(.heavy))
                .kerning(0.5)
                .foregroundColor(LCARS.space)
                .padding(.horizontal, 18)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity)
                .background(color)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

/// Dark monospace readout panel (the LCARS status/log look).
struct ReadoutPanel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(LCARS.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(LCARS.blue.opacity(0.35), lineWidth: 1))
    }
}

/// The LCARS "elbow" header sweep.
struct LcarsHeader: View {
    let title: String
    let subtitle: String
    var body: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 8)
                .fill(LCARS.orange)
                .frame(width: 60, height: 26)
            VStack(alignment: .leading, spacing: 0) {
                Text(title.uppercased())
                    .font(.system(.title2, design: .rounded).weight(.heavy))
                    .kerning(1)
                    .foregroundColor(LCARS.gold)
                Text(subtitle.uppercased())
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .kerning(1)
                    .foregroundColor(LCARS.lilac)
            }
            Spacer()
            RoundedRectangle(cornerRadius: 8)
                .fill(LCARS.blue)
                .frame(width: 120, height: 14)
        }
    }
}
