package tools.jackson.databind.deser.jdk;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.annotation.JsonView;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Unit tests for {@link ThrowableDeserializer#deserializeFromObject}: verifies
 * deserialization of Throwable types from JSON objects, covering the standard
 * properties ("message", "cause", "suppressed", "stackTrace", "localizedMessage"),
 * deferred handling of properties that appear before "message", view-based
 * exclusion, ignorable/unknown property handling, and instantiation requirements.
 */
public class DeserializeFromObjectTests
{
    private final JsonMapper MAPPER = new JsonMapper();

    /*
    /**********************************************************************
    /* Helper entity classes
    /**********************************************************************
     */

    /**
     * Throwable with default constructor but no single-String constructor:
     * instance can be created, but "message" can not be assigned.
     */
    public static class DefaultCtorOnlyThrowable extends Exception {
        public DefaultCtorOnlyThrowable() { }
    }

    /**
     * Throwable with both default and single-String constructors, plus a
     * custom settable property to exercise deferred (pending) property handling.
     */
    public static class NamedThrowable extends Exception {
        public String name;

        public NamedThrowable() { }

        public NamedThrowable(String msg) { super(msg); }
    }

    /**
     * Throwable with neither default nor single-String constructor: should
     * fail with a missing-instantiator exception.
     */
    public static class NoUsableCtorThrowable extends Exception {
        public NoUsableCtorThrowable(String msg, int code) {
            super(msg + "/" + code);
        }
    }

    public static class ViewA { }

    public static class ViewB { }

    public static class ViewedThrowable extends Exception {
        @JsonView(ViewA.class)
        public int onlyInViewA;
    }

    /*
    /**********************************************************************
    /* Basic functionality
    /**********************************************************************
     */

    @Test
    public void testSimpleMessage() throws Exception {
        Exception result = MAPPER.readValue("{\"message\":\"the message\"}",
                Exception.class);
        assertEquals("the message", result.getMessage());
    }

    @Test
    public void testEmptyObject() throws Exception {
        Exception result = MAPPER.readValue("{}", Exception.class);
        assertNotNull(result);
        assertNull(result.getMessage());
    }

    @Test
    public void testNullMessage() throws Exception {
        Exception result = MAPPER.readValue("{\"message\":null}", Exception.class);
        assertNotNull(result);
        assertNull(result.getMessage());
    }

    /*
    /**********************************************************************
    /* Regular (indexed) properties: deferred and direct handling
    /**********************************************************************
     */

    @Test
    public void testCustomPropertyBeforeMessage() throws Exception {
        // Property appearing before "message" must be deferred (buffered)
        // and applied after the instance has been created
        NamedThrowable result = MAPPER.readValue(
                "{\"name\":\"Bob\",\"message\":\"hello\"}", NamedThrowable.class);
        assertEquals("hello", result.getMessage());
        assertEquals("Bob", result.name);
    }

    @Test
    public void testCustomPropertyAfterMessage() throws Exception {
        // Property appearing after "message" can be set directly
        NamedThrowable result = MAPPER.readValue(
                "{\"message\":\"hello\",\"name\":\"Bob\"}", NamedThrowable.class);
        assertEquals("hello", result.getMessage());
        assertEquals("Bob", result.name);
    }

    @Test
    public void testCauseBeforeMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}",
                Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getCause());
        assertEquals("inner", result.getCause().getMessage());
    }

    @Test
    public void testCauseAfterMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":{\"message\":\"inner\"}}",
                Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getCause());
        assertEquals("inner", result.getCause().getMessage());
    }

    // [databind#4248]: null "cause" (and "stackTrace") values must be skipped,
    // not passed to initCause()/setStackTrace() (which would fail)
    @Test
    public void testNullCauseAndStackTraceSkipped() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":null,\"stackTrace\":null}",
                Exception.class);
        assertEquals("outer", result.getMessage());
        assertNull(result.getCause());
    }

    /*
    /**********************************************************************
    /* Standard Throwable properties
    /**********************************************************************
     */

    @Test
    public void testSuppressedExceptions() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":"
                + "[{\"message\":\"s1\"},{\"message\":\"s2\"}]}",
                Exception.class);
        assertEquals("main", result.getMessage());
        assertEquals(2, result.getSuppressed().length);
        assertEquals("s1", result.getSuppressed()[0].getMessage());
        assertEquals("s2", result.getSuppressed()[1].getMessage());
    }

    @Test
    public void testSuppressedBeforeMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"suppressed\":[{\"message\":\"s1\"}],\"message\":\"main\"}",
                Exception.class);
        assertEquals("main", result.getMessage());
        assertEquals(1, result.getSuppressed().length);
        assertEquals("s1", result.getSuppressed()[0].getMessage());
    }

    @Test
    public void testNullSuppressed() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":null}", Exception.class);
        assertEquals("main", result.getMessage());
        assertEquals(0, result.getSuppressed().length);
    }

    @Test
    public void testStackTrace() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"boom\",\"stackTrace\":["
                + "{\"className\":\"java.lang.Exception\",\"methodName\":\"run\","
                + "\"fileName\":\"App.java\",\"lineNumber\":42}]}",
                Exception.class);
        assertEquals(1, result.getStackTrace().length);
        assertEquals("java.lang.Exception", result.getStackTrace()[0].getClassName());
        assertEquals("run", result.getStackTrace()[0].getMethodName());
        assertEquals("App.java", result.getStackTrace()[0].getFileName());
        assertEquals(42, result.getStackTrace()[0].getLineNumber());
    }

    @Test
    public void testLocalizedMessageIgnored() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"plain\",\"localizedMessage\":\"localized\"}",
                Exception.class);
        assertEquals("plain", result.getMessage());
    }

    // Standard Throwable property names are matched case-insensitively
    @Test
    public void testStdPropertyNamesCaseInsensitive() throws Exception {
        Exception result = MAPPER.readValue("{\"MESSAGE\":\"loud\"}", Exception.class);
        assertEquals("loud", result.getMessage());
    }

    /*
    /**********************************************************************
    /* Unknown / ignorable properties
    /**********************************************************************
     */

    @Test
    public void testUnknownPropertyIgnoredWhenConfigured() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        Exception result = mapper.readValue(
                "{\"message\":\"x\",\"unknownProp\":42}", Exception.class);
        assertEquals("x", result.getMessage());
    }

    @Test
    public void testUnknownPropertyFailsWhenEnabled() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        try {
            mapper.readValue("{\"message\":\"x\",\"unknownProp\":42}", Exception.class);
            fail("Should have failed on unknown property");
        } catch (JacksonException e) {
            // expected
        }
    }

    /*
    /**********************************************************************
    /* Instantiation requirements
    /**********************************************************************
     */

    @Test
    public void testMissingInstantiator() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"x\"}", NoUsableCtorThrowable.class);
            fail("Should have failed without usable constructor");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testMessageWithoutStringCreatorUsesDefaultCtor() throws Exception {
        // Without a single-String constructor "message" can not be assigned;
        // instance is still created via the default constructor
        DefaultCtorOnlyThrowable result = MAPPER.readValue(
                "{\"message\":\"dropped\"}", DefaultCtorOnlyThrowable.class);
        assertNotNull(result);
        assertNull(result.getMessage());
    }

    /*
    /**********************************************************************
    /* View handling
    /**********************************************************************
     */

    @Test
    public void testViewFiltering() throws Exception {
        // Without an active view nothing is excluded
        ViewedThrowable noView = MAPPER.readValue(
                "{\"onlyInViewA\":42}", ViewedThrowable.class);
        assertEquals(42, noView.onlyInViewA);

        // Matching view: property set
        ViewedThrowable inA = MAPPER.readerFor(ViewedThrowable.class)
                .withView(ViewA.class)
                .readValue("{\"onlyInViewA\":42}");
        assertEquals(42, inA.onlyInViewA);

        // Non-matching view: property must not be set from input
        ViewedThrowable inB = MAPPER.readerFor(ViewedThrowable.class)
                .withView(ViewB.class)
                .readValue("{\"onlyInViewA\":42}");
        assertEquals(0, inB.onlyInViewA);
    }
}