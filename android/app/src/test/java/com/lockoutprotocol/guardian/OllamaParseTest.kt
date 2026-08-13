package com.lockoutprotocol.guardian

import com.lockoutprotocol.guardian.ai.OllamaClient
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OllamaParseTest {

    /** Wrap a model "content" string in the Ollama /api/chat response envelope. */
    private fun body(content: String) =
        """{"message":{"role":"assistant","content":${JSONObject.quote(content)}}}"""

    @Test
    fun parsesViolationTrue() {
        val v = OllamaClient.parseVerdict(body("""{"violation": true, "reason": "nudity"}"""))
        assertTrue(v.violation)
        assertFalse(v.undetermined)
        assertEquals("nudity", v.reason)
    }

    @Test
    fun parsesCategory() {
        val v = OllamaClient.parseVerdict(
            body("""{"violation": true, "category": "Search", "reason": "typed a query"}"""))
        assertTrue(v.violation)
        assertEquals("search", v.category)
    }

    @Test
    fun missingCategoryIsBlankNotGuessed() {
        val v = OllamaClient.parseVerdict(body("""{"violation": true, "reason": "bikini photo"}"""))
        assertTrue(v.violation)
        assertEquals("", v.category)
    }

    @Test
    fun parsesViolationFalse() {
        val v = OllamaClient.parseVerdict(body("""{"violation": false, "reason": "safe"}"""))
        assertFalse(v.violation)
        assertFalse(v.undetermined)
    }

    @Test
    fun unparseableContentIsUndetermined() {
        val v = OllamaClient.parseVerdict("this is not json at all")
        assertTrue(v.undetermined)
        assertFalse(v.violation)
    }

    @Test
    fun missingFieldsDefaultToSafeNotUndetermined() {
        val v = OllamaClient.parseVerdict(body("""{"foo":"bar"}"""))
        assertFalse(v.violation)
        assertFalse(v.undetermined)
    }

    @Test
    fun handlesContentWithWhitespace() {
        val v = OllamaClient.parseVerdict(body("\n  {\"violation\": true, \"reason\": \"x\"}  \n"))
        assertTrue(v.violation)
    }
}
