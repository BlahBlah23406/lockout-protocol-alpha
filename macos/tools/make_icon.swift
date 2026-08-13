import AppKit
import CoreGraphics

// Renders a 1024×1024 Guardian app icon (a simple shield) to tools/AppIcon_1024.png.
// Run:  swift tools/make_icon.swift

let S: CGFloat = 1024
let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(S), pixelsHigh: Int(S),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

func color(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor {
    CGColor(red: r/255, green: g/255, blue: b/255, alpha: a)
}
let space    = color(0x05, 0x07, 0x0D)
let spaceTop = color(0x12, 0x1A, 0x33)
let orange   = color(0xFF, 0x99, 0x66)
let orangeDk = color(0xE0, 0x77, 0x44)

// ---- Rounded "squircle" app tile with a vertical space gradient ----------------------------
let inset: CGFloat = 76
let tile = CGRect(x: inset, y: inset, width: S - 2*inset, height: S - 2*inset)
let tilePath = CGPath(roundedRect: tile, cornerWidth: 224, cornerHeight: 224, transform: nil)
ctx.saveGState()
ctx.addPath(tilePath); ctx.clip()
let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                      colors: [spaceTop, space] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(grad, start: CGPoint(x: 0, y: S), end: CGPoint(x: 0, y: 0), options: [])
ctx.restoreGState()

// ---- Shield (centered, the whole icon) -----------------------------------------------------
// CoreGraphics y is bottom-up: flat top is HIGH, point is LOW.
let cx: CGFloat = 512
let topFlatY: CGFloat = 762
let hw: CGFloat = 270
let shoulderY: CGFloat = 540
let pointY: CGFloat = 250
let shield = CGMutablePath()
let r: CGFloat = 54
shield.move(to: CGPoint(x: cx - hw + r, y: topFlatY))
shield.addLine(to: CGPoint(x: cx + hw - r, y: topFlatY))
shield.addArc(tangent1End: CGPoint(x: cx + hw, y: topFlatY),
              tangent2End: CGPoint(x: cx + hw, y: topFlatY - r), radius: r)
shield.addLine(to: CGPoint(x: cx + hw, y: shoulderY))
shield.addQuadCurve(to: CGPoint(x: cx, y: pointY), control: CGPoint(x: cx + hw, y: pointY + 64))
shield.addQuadCurve(to: CGPoint(x: cx - hw, y: shoulderY), control: CGPoint(x: cx - hw, y: pointY + 64))
shield.addLine(to: CGPoint(x: cx - hw, y: topFlatY - r))
shield.addArc(tangent1End: CGPoint(x: cx - hw, y: topFlatY),
              tangent2End: CGPoint(x: cx - hw + r, y: topFlatY), radius: r)
shield.closeSubpath()

ctx.saveGState()
ctx.addPath(shield); ctx.clip()
let sgrad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                       colors: [orange, orangeDk] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(sgrad, start: CGPoint(x: 0, y: topFlatY), end: CGPoint(x: 0, y: pointY), options: [])
ctx.restoreGState()

NSGraphicsContext.restoreGraphicsState()

let outURL = URL(fileURLWithPath: "tools/AppIcon_1024.png")
let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: outURL)
print("wrote \(outURL.path)")
