package com.lockoutprotocol.guardian

import com.lockoutprotocol.guardian.capture.FrameQuality
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FrameQualityTest {

    @Test
    fun allBlackIsUnreadable() {
        assertTrue(FrameQuality.isUnreadableLuminance(IntArray(1000) { 0 }))
    }

    @Test
    fun uniformGreyIsUnreadable() {
        assertTrue(FrameQuality.isUnreadableLuminance(IntArray(1000) { 128 }))
    }

    @Test
    fun emptyIsUnreadable() {
        assertTrue(FrameQuality.isUnreadableLuminance(IntArray(0)))
    }

    @Test
    fun mostlyBlackWithTinyContentIsUnreadable() {
        // 99.7% black -> blackFraction > 0.995
        assertTrue(FrameQuality.isUnreadableLuminance(IntArray(1000) { if (it < 3) 200 else 0 }))
    }

    @Test
    fun variedContentIsReadable() {
        // Alternating dark/bright -> high variance -> real content.
        assertFalse(FrameQuality.isUnreadableLuminance(IntArray(1000) { if (it % 2 == 0) 10 else 220 }))
    }

    @Test
    fun darkModeWithTextIsReadable() {
        // Mostly dark (~30) but with scattered bright text pixels -> enough variance.
        assertFalse(FrameQuality.isUnreadableLuminance(IntArray(1000) { if (it % 7 == 0) 230 else 30 }))
    }
}
