package tools.jackson.databind.deser.jdk;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

/**
 * Unit tests for "ThrowableDeserializer.deserializeFromObject", exercised
 * through the public JsonMapper API with JSON content. Configuration that
 * affects behavior is set explicitly so tests do not depend on defaults.
 */
public class DeserializeFromObjectTests
{
    private JsonMapper defaultMapper() {
        return JsonMapper.builder().build();
    }

    private JsonMapper lenientMapper() {
        return JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
    }

    private JsonMapper strictMapper() {
        return JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
    }

    // Helper classes covering various Throwable flavors

    public static class CustomPropException extends RuntimeException {
        protected int errorCode;

        public CustomPropException() { }

        public CustomPropException(String message) { super(message); }

        public int getErrorCode() { return errorCode; }

        public void setErrorCode(int v) { errorCode = v; }
    }

    public static class CreatorException extends RuntimeException {
        protected final int code;

        @JsonCreator
        public CreatorException(@JsonProperty("message") String message,
                @JsonProperty("code") int code) {
            super(message);
            this.code = code;
        }

        public int getCode() { return code; }
    }

    public static class DefaultCtorOnlyException extends RuntimeException {
        public DefaultCtorOnlyException() { }
    }

    public static class NoDefaultCtorException extends Exception {
        public NoDefaultCtorException(String message, int code) {
            super(message);
        }
    }

    public abstract static class AbstractThrowableException extends RuntimeException {
        public AbstractThrowableException() { }

        public AbstractThrowableException(String message) { super(message); }
    }

    @Test
    public void testMessageOnlyForThrowable() throws Exception {
        Throwable t = defaultMapper().readValue(
                "{\"message\":\"t-msg\"}", Throwable.class);
        assertEquals("t-msg", t.getMessage());
        assertNull(t.getCause());
    }

    @Test
    public void testMessageOnlyForRuntimeException() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"runtime-msg\"}", RuntimeException.class);
        assertEquals("runtime-msg", e.getMessage());

        // Also for a more specific standard Throwable subtype
        IllegalStateException e2 = defaultMapper().readValue(
                "{\"message\":\"illegal-state\"}", IllegalStateException.class);
        assertEquals("illegal-state", e2.getMessage());
    }

    @Test
    public void testEmptyObjectGivesThrowableWithoutMessage() throws Exception {
        RuntimeException e = defaultMapper().readValue("{}", RuntimeException.class);
        assertNotNull(e);
        assertNull(e.getMessage());
        assertNull(e.getCause());
    }

    @Test
    public void testMessageWithNestedCause() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"outer\",\"cause\":{\"message\":\"inner\"}}",
                RuntimeException.class);
        assertEquals("outer", e.getMessage());
        Throwable cause = e.getCause();
        assertNotNull(cause);
        assertEquals("inner", cause.getMessage());
    }

    @Test
    public void testCauseBeforeMessageIsAppliedAfterInstantiation() throws Exception {
        // "cause" appears before "message": its value must be buffered
        // ("pending") and set once the Throwable has been instantiated
        RuntimeException e = defaultMapper().readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}",
                RuntimeException.class);
        assertEquals("outer", e.getMessage());
        Throwable cause = e.getCause();
        assertNotNull(cause);
        assertEquals("inner", cause.getMessage());
    }

    @Test
    public void testNullValuesForCauseAndStackTraceAndSuppressedSkipped() throws Exception {
        // [databind#4248]: explicit JSON nulls for "cause" and "stackTrace"
        // must be skipped instead of being passed to setters that cannot
        // accept nulls; "suppressed":null simply means no suppressed entries
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"cause\":null,\"stackTrace\":null,\"suppressed\":null}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
        assertNull(e.getCause());
        assertEquals(0, e.getSuppressed().length);
    }

    @Test
    public void testSuppressedExceptionsDeserialized() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"suppressed\":[{\"message\":\"s1\"},{\"message\":\"s2\"}]}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
        assertEquals(2, e.getSuppressed().length);
        assertEquals("s1", e.getSuppressed()[0].getMessage());
        assertEquals("s2", e.getSuppressed()[1].getMessage());
    }

    @Test
    public void testSuppressedBeforeMessage() throws Exception {
        // "suppressed" collected before instantiation must still be added
        RuntimeException e = defaultMapper().readValue(
                "{\"suppressed\":[{\"message\":\"s1\"}],\"message\":\"m\"}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
        assertEquals(1, e.getSuppressed().length);
        assertEquals("s1", e.getSuppressed()[0].getMessage());
    }

    @Test
    public void testNullSuppressedArrayIgnored() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"suppressed\":null}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
        assertEquals(0, e.getSuppressed().length);
    }

    @Test
    public void testNullEntriesInSuppressedSkipped() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"suppressed\":[null,{\"message\":\"only\"}]}",
                RuntimeException.class);
        assertEquals(1, e.getSuppressed().length);
        assertEquals("only", e.getSuppressed()[0].getMessage());
    }

    @Test
    public void testLocalizedMessageSkipped() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"localizedMessage\":\"should-not-be-used\"}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
        assertEquals("m", e.getLocalizedMessage());

        // Structured value for "localizedMessage" must be skipped as a whole
        RuntimeException e2 = defaultMapper().readValue(
                "{\"localizedMessage\":{\"anything\":3},\"message\":\"m2\"}",
                RuntimeException.class);
        assertEquals("m2", e2.getMessage());
    }

    @Test
    public void testStackTraceDeserialized() throws Exception {
        RuntimeException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"stackTrace\":"
                + "[{\"className\":\"java.lang.Thread\",\"methodName\":\"sleep\","
                + "\"fileName\":\"Thread.java\",\"lineNumber\":42}]}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
        assertEquals(1, e.getStackTrace().length);
        assertEquals("java.lang.Thread", e.getStackTrace()[0].getClassName());
        assertEquals("sleep", e.getStackTrace()[0].getMethodName());
        assertEquals("Thread.java", e.getStackTrace()[0].getFileName());
        assertEquals(42, e.getStackTrace()[0].getLineNumber());
    }

    @Test
    public void testUnknownPropertyIgnoredWhenLenient() throws Exception {
        RuntimeException e = lenientMapper().readValue(
                "{\"message\":\"m\",\"unknownProp\":true}",
                RuntimeException.class);
        assertEquals("m", e.getMessage());
    }

    @Test
    public void testUnknownPropertyFailsWhenStrict() throws Exception {
        try {
            strictMapper().readValue(
                    "{\"message\":\"m\",\"unknownProp\":true}",
                    RuntimeException.class);
            fail("Should have failed on unknown property in strict mode");
        } catch (JacksonException e) {
            assertNotNull(e.getMessage());
        }
    }

    @Test
    public void testCustomPropertyBeforeAndAfterMessage() throws Exception {
        CustomPropException e = defaultMapper().readValue(
                "{\"message\":\"m\",\"errorCode\":42}",
                CustomPropException.class);
        assertEquals("m", e.getMessage());
        assertEquals(42, e.getErrorCode());

        // Property before "message": buffered, applied after instantiation
        CustomPropException e2 = defaultMapper().readValue(
                "{\"errorCode\":7,\"message\":\"m2\"}",
                CustomPropException.class);
        assertEquals("m2", e2.getMessage());
        assertEquals(7, e2.getErrorCode());
    }

    @Test
    public void testPropertyBasedCreatorDelegation() throws Exception {
        CreatorException e = defaultMapper().readValue(
                "{\"message\":\"creator-msg\",\"code\":13}",
                CreatorException.class);
        assertEquals("creator-msg", e.getMessage());
        assertEquals(13, e.getCode());
    }

    @Test
    public void testMessageSkippedForDefaultCtorOnlyThrowable() throws Exception {
        // No single-String constructor: instantiation via default constructor,
        // "message" cannot be assigned and is skipped without failure
        DefaultCtorOnlyException e = defaultMapper().readValue(
                "{\"message\":\"m\"}",
                DefaultCtorOnlyException.class);
        assertNotNull(e);
        assertNull(e.getMessage());
    }

    @Test
    public void testThrowableWithoutUsableConstructorsFails() throws Exception {
        try {
            defaultMapper().readValue(
                    "{\"message\":\"m\"}", NoDefaultCtorException.class);
            fail("Should not allow Throwable without default or single-String constructor");
        } catch (JacksonException e) {
            assertNotNull(e.getMessage());
        }
    }

    @Test
    public void testAbstractThrowableTypeFails() throws Exception {
        try {
            defaultMapper().readValue(
                    "{\"message\":\"m\"}", AbstractThrowableException.class);
            fail("Should not allow abstract Throwable type without type information");
        } catch (JacksonException e) {
            assertNotNull(e.getMessage());
        }
    }
}