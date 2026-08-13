package com.lockoutprotocol.guardian.capture

import android.graphics.Bitmap
import kotlin.math.max

/**
 * Heuristic: is this frame essentially blank/uniform — i.e. there is nothing for the AI to see?
 *
 * Apps that set FLAG_SECURE (banking, DRM video, some messengers) come back from the screenshot
 * API as a solid black (or occasionally solid colour) frame. A failed capture is similar. In
 * those cases we cannot verify the content, so the caller blocks (fail closed).
 *
 * We sample a coarse grid and flag the frame if it is almost entirely near-black OR almost
 * perfectly uniform (variance ~0). Real screens — even dark-mode ones — carry text/icons that
 * push variance well above the threshold, so this stays conservative.
 */
object FrameQuality {

    fun isUnreadable(bmp: Bitmap): Boolean {
        val stepX = max(1, bmp.width / 32)
        val stepY = max(1, bmp.height / 32)
        val lums = ArrayList<Int>(1024)

        var x = 0
        while (x < bmp.width) {
            var y = 0
            while (y < bmp.height) {
                val c = bmp.getPixel(x, y)
                val r = (c shr 16) and 0xFF
                val g = (c shr 8) and 0xFF
                val b = c and 0xFF
                lums.add((r * 299 + g * 587 + b * 114) / 1000)
                y += stepY
            }
            x += stepX
        }
        return isUnreadableLuminance(lums.toIntArray())
    }

    /** Pure heuristic over sampled luminance values (0..255). Extracted so it is unit-testable. */
    fun isUnreadableLuminance(lums: IntArray): Boolean {
        if (lums.isEmpty()) return true
        var nearBlack = 0
        var sum = 0L
        var sumSq = 0L
        for (lum in lums) {
            if (lum < 16) nearBlack++
            sum += lum
            sumSq += (lum * lum).toLong()
        }
        val n = lums.size
        val mean = sum.toDouble() / n
        val variance = sumSq.toDouble() / n - mean * mean
        val blackFraction = nearBlack.toDouble() / n
        return blackFraction > 0.995 || variance < 4.0
    }
}
