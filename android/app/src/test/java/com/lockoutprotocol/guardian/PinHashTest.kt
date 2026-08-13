package com.lockoutprotocol.guardian

import com.lockoutprotocol.guardian.data.Prefs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class PinHashTest {

    @Test
    fun sha256_matchesKnownVector() {
        // SHA-256("1234")
        assertEquals(
            "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4",
            Prefs.sha256("1234")
        )
    }

    @Test
    fun sha256_differsForDifferentPins() {
        assertNotEquals(Prefs.sha256("1234"), Prefs.sha256("1235"))
    }

    @Test
    fun sha256_isStable() {
        assertEquals(Prefs.sha256("9999"), Prefs.sha256("9999"))
    }
}
