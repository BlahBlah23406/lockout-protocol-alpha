package com.lockoutprotocol.guardian

import com.lockoutprotocol.guardian.ai.AlertPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AlertPolicyTest {

    @Test
    fun deliberateCategoriesAlwaysAlertEvenWithSuggestiveOff() {
        for (c in listOf("tamper", "search", "site", "explicit")) {
            assertTrue(c, AlertPolicy.shouldAlert(c, alertOnSuggestive = false))
        }
    }

    @Test
    fun suggestiveIsQuietByDefaultButRespectsTheSetting() {
        assertFalse(AlertPolicy.shouldAlert("suggestive", alertOnSuggestive = false))
        assertTrue(AlertPolicy.shouldAlert("suggestive", alertOnSuggestive = true))
    }

    @Test
    fun unclassifiedViolationsStillAlert() {
        assertTrue(AlertPolicy.shouldAlert("", alertOnSuggestive = false))
        assertTrue(AlertPolicy.shouldAlert("something-weird", alertOnSuggestive = false))
    }

    @Test
    fun normalizeAcceptsExactLabelsAndCase() {
        assertEquals("tamper", AlertPolicy.normalize("Tamper"))
        assertEquals("explicit", AlertPolicy.normalize("  EXPLICIT "))
        assertEquals("suggestive", AlertPolicy.normalize("suggestive"))
    }

    @Test
    fun normalizeMapsNearMissesOntoTheVocabulary() {
        assertEquals("tamper", AlertPolicy.normalize("tampering"))
        assertEquals("search", AlertPolicy.normalize("search_intent"))
        assertEquals("site", AlertPolicy.normalize("porn site"))
        assertEquals("explicit", AlertPolicy.normalize("nudity"))
        assertEquals("suggestive", AlertPolicy.normalize("mildly suggestive"))
    }

    @Test
    fun normalizeReturnsBlankForNonsense() {
        assertEquals("", AlertPolicy.normalize("banana"))
        assertEquals("", AlertPolicy.normalize(null))
        assertEquals("", AlertPolicy.normalize(""))
    }
}
