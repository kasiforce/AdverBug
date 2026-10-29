package tools.jackson.databind.deser.jdk;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Tests for {@link ThrowableDeserializer#deserializeFromObject}, exercising
 * standard Throwable properties ("message", "cause", "suppressed",
 * "stackTrace", "localizedMessage"), deferred ("pending") property handling,
 * view/ignore filtering, any-setter, unknown-property handling, and
 * instantiation failure cases.
 */
public class DeserializeFromObjectTests
{
    private final JsonMapper MAPPER = JsonMapper.builder().build();

    /*
    /**********************************************************************
    /* Basic functionality
    /**********************************************************************
     */

    // Instantiation via single-String-arg constructor from "message"
    @Test
    public void testSimpleExceptionFromMessage() throws Exception {
        Exception result = MAPPER.readValue("{\"message\":\"foobar\"}", Exception.class);
        assertEquals("foobar", result.getMessage());
    }

    // Empty Object: instantiated with default/no-arg constructor, null message
    @Test
    public void testEmptyObjectDefaultsToNullMessage() throws Exception {
        Exception result = MAPPER.readValue("{}", Exception.class);
        assertNotNull(result);
        assertNull(result.getMessage());
    }

    /*
    /**********************************************************************
    /* Deferred ("pending") properties, set after instantiation
    /**********************************************************************
     */

    @Test
    public void testCustomExceptionPropertyBeforeMessage() throws Exception {
        SampleException result = MAPPER.readValue(
                "{\"code\":42,\"message\":\"boom\"}", SampleException.class);
        assertEquals("boom", result.getMessage());
        assertEquals(42, result.getCode());
    }

    @Test
    public void testCustomExceptionPropertyAfterMessage() throws Exception {
        SampleException result = MAPPER.readValue(
                "{\"message\":\"boom\",\"code\":42}", SampleException.class);
        assertEquals("boom", result.getMessage());
        assertEquals(42, result.getCode());
    }

    // "stackTrace" appearing before "message" must be deferred, then applied
    @Test
    public void testStackTraceDeferredUntilMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"stackTrace\":[],\"message\":\"deferred\"}", Exception.class);
        assertEquals("deferred", result.getMessage());
        assertEquals(0, result.getStackTrace().length);
    }

    @Test
    public void testCauseDeserialization() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":{\"message\":\"inner\"}}", Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getCause());
        assertEquals("inner", result.getCause().getMessage());
    }

    @Test
    public void testCauseBeforeMessageAppliedAfterInstantiation() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}", Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getCause());
        assertEquals("inner", result.getCause().getMessage());
    }

    /*
    /**********************************************************************
    /* Null-value skipping ([databind#4248])
    /**********************************************************************
     */

    @Test
    public void testNullCauseIsSkipped() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":null}", Exception.class);
        assertEquals("outer", result.getMessage());
        assertNull(result.getCause());
    }

    @Test
    public void testNullStackTraceIsSkipped() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"outer\",\"stackTrace\":null}", Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getStackTrace());
    }

    /*
    /**********************************************************************
    /* Suppressed exceptions
    /**********************************************************************
     */

    @Test
    public void testSuppressedExceptionsDeserialized() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":[{\"message\":\"first\"},{\"message\":\"second\"}]}",
                Exception.class);
        assertEquals("main", result.getMessage());
        assertEquals(2, result.getSuppressed().length);
        assertEquals("first", result.getSuppressed()[0].getMessage());
        assertEquals("second", result.getSuppressed()[1].getMessage());
    }

    @Test
    public void testSuppressedNullIsIgnored() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":null}", Exception.class);
        assertEquals("main", result.getMessage());
        assertEquals(0, result.getSuppressed().length);
    }

    /*
    /**********************************************************************
    /* "localizedMessage" is skipped
    /**********************************************************************
     */

    @Test
    public void testLocalizedMessageIsSkipped() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"real\",\"localizedMessage\":\"fake\"}", Exception.class);
        assertEquals("real", result.getMessage());
    }

    /*
    /**********************************************************************
    /* Unknown / ignorable properties
    /**********************************************************************
     */

    @Test
    public void testUnknownPropertyIgnoredWhenConfiguredLenient() throws Exception {
        JsonMapper lenientMapper = JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        Exception result = lenientMapper.readValue(
                "{\"message\":\"main\",\"unknownStuff\":42}", Exception.class);
        assertEquals("main", result.getMessage());
    }

    @Test
    public void testUnknownPropertyFailsWhenConfiguredStrict() throws Exception {
        JsonMapper strictMapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        try {
            strictMapper.readValue("{\"message\":\"main\",\"unknownStuff\":42}", Exception.class);
            fail("Expected an exception for unknown property");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testIgnorablePropertySkippedEvenWhenStrict() throws Exception {
        JsonMapper strictMapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        IgnorableException result = strictMapper.readValue(
                "{\"message\":\"main\",\"junk\":\"x\"}", IgnorableException.class);
        assertEquals("main", result.getMessage());
    }

    // Standard Throwable properties are processed before ignore lists
    // are consulted, so "suppressed" must not be dropped ([databind#6157])
    @Test
    public void testStandardSuppressedNotDroppedByIgnorableProps() throws Exception {
        JsonMapper strictMapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        IgnoreSuppressedException result = strictMapper.readValue(
                "{\"message\":\"main\",\"suppressed\":[{\"message\":\"inner\"}]}",
                IgnoreSuppressedException.class);
        assertEquals("main", result.getMessage());
        assertEquals(1, result.getSuppressed().length);
        assertEquals("inner", result.getSuppressed()[0].getMessage());
    }

    @Test
    public void testAnySetterCapturesUnknownProperties() throws Exception {
        AnySetException result = MAPPER.readValue(
                "{\"message\":\"main\",\"extra1\":\"v1\"}", AnySetException.class);
        assertEquals("main", result.getMessage());
        assertEquals("v1", result.extras.get("extra1"));
    }

    /*
    /**********************************************************************
    /* Instantiation failure cases
    /**********************************************************************
     */

    // Abstract Throwable type must fail with "missing instantiator"
    @Test
    public void testAbstractThrowableTypeFails() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"main\"}", AbstractSampleException.class);
            fail("Expected an exception for abstract Throwable type");
        } catch (JacksonException e) {
            // expected
        }
    }

    // No default constructor, no single-String-arg constructor: must fail
    @Test
    public void testThrowableWithoutUsableConstructorFails() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"main\"}", NoDefaultConstructorException.class);
            fail("Expected an exception for Throwable without usable constructor");
        } catch (JacksonException e) {
            // expected
        }
    }

    /*
    /**********************************************************************
    /* Helper types
    /**********************************************************************
     */

    public static class SampleException extends Exception {
        private int code;

        public SampleException() { }

        public SampleException(String message) { super(message); }

        public int getCode() { return code; }

        public void setCode(int code) { this.code = code; }
    }

    @JsonIgnoreProperties({ "junk" })
    public static class IgnorableException extends Exception {
        public IgnorableException() { }

        public IgnorableException(String message) { super(message); }
    }

    @JsonIgnoreProperties({ "suppressed" })
    public static class IgnoreSuppressedException extends Exception {
        public IgnoreSuppressedException() { }

        public IgnoreSuppressedException(String message) { super(message); }
    }

    public static class AnySetException extends Exception {
        private final Map<String, Object> extras = new LinkedHashMap<String, Object>();

        public AnySetException() { }

        public AnySetException(String message) { super(message); }

        @JsonAnySetter
        public void addExtra(String key, Object value) {
            extras.put(key, value);
        }
    }

    public static abstract class AbstractSampleException extends Exception {
        public AbstractSampleException() { }

        public AbstractSampleException(String message) { super(message); }
    }

    public static class NoDefaultConstructorException extends Exception {
        public NoDefaultConstructorException(int code) {
            super("code=" + code);
        }
    }
}