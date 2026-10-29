package tools.jackson.databind.deser.jdk;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Unit tests for {@code ThrowableDeserializer#deserializeFromObject}, exercised
 * through the public data-binding API ({@link ObjectMapper}).
 */
public class DeserializeFromObjectTests
{
    private final ObjectMapper STRICT_MAPPER = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    private final ObjectMapper LENIENT_MAPPER = JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    // View marker classes
    public static class ViewA { }
    public static class ViewB { }

    // Only has the implicit default constructor
    public static class DefaultCtorException extends Exception { }

    // Only has a single-int-arg constructor: no default ctor, no single-String ctor
    public static class NoCreatorException extends Exception {
        public NoCreatorException(int value) {
            super("value=" + value);
        }
    }

    @JsonIgnoreProperties({ "ignoreMe" })
    public static class IgnoringException extends Exception {
        public IgnoringException() { }
        public IgnoringException(String msg) { super(msg); }
    }

    @JsonIgnoreProperties({ "message" })
    public static class IgnoreMessageException extends Exception {
        public IgnoreMessageException() { }
        public IgnoreMessageException(String msg) { super(msg); }
    }

    public static class AnySetterException extends Exception {
        protected Map<String, Object> _extras = new LinkedHashMap<String, Object>();

        public AnySetterException() { }

        public AnySetterException(String msg) { super(msg); }

        @JsonAnySetter
        public void addExtra(String key, Object value) {
            _extras.put(key, value);
        }

        public Map<String, Object> getExtras() {
            return _extras;
        }
    }

    public static class ViewedException extends Exception {
        protected int _code;

        public ViewedException() { }

        public ViewedException(String msg) { super(msg); }

        @JsonView(ViewA.class)
        public void setCode(int code) { _code = code; }

        public int getCode() { return _code; }
    }

    public static class CreatorException extends Exception {
        @JsonCreator
        public CreatorException(@JsonProperty("message") String msg) {
            super(msg);
        }
    }

    public static class DelegateException extends Exception {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public DelegateException(Map<String, Object> props) {
            super(String.valueOf(props.get("message")));
        }
    }

    public abstract static class AbstractThrowable extends Exception { }

    /*
    /**********************************************************************
    /* Basic functionality
    /**********************************************************************
     */

    @Test
    public void testSimpleMessage() throws Exception {
        Exception ex = STRICT_MAPPER.readValue("{\"message\":\"boom\"}", Exception.class);
        assertEquals("boom", ex.getMessage());
    }

    @Test
    public void testMessageAndCause() throws Exception {
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":{\"message\":\"inner\"}}",
                Exception.class);
        assertEquals("outer", ex.getMessage());
        assertNotNull(ex.getCause());
        assertEquals("inner", ex.getCause().getMessage());
    }

    @Test
    public void testCauseBeforeMessage() throws Exception {
        // "cause" appearing before "message" must be buffered ("pending") and
        // applied after the Throwable instance has been created
        Exception ex = STRICT_MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}",
                Exception.class);
        assertEquals("outer", ex.getMessage());
        assertNotNull(ex.getCause());
        assertEquals("inner", ex.getCause().getMessage());
    }

    @Test
    public void testStackTraceIsSet() throws Exception {
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\","
                + "\"stackTrace\":[{\"className\":\"java.lang.Foo\",\"methodName\":\"bar\","
                + "\"fileName\":\"Foo.java\",\"lineNumber\":42}]}",
                Exception.class);
        assertEquals("boom", ex.getMessage());
        assertEquals(1, ex.getStackTrace().length);
        StackTraceElement elem = ex.getStackTrace()[0];
        assertEquals("java.lang.Foo", elem.getClassName());
        assertEquals("bar", elem.getMethodName());
        assertEquals("Foo.java", elem.getFileName());
        assertEquals(42, elem.getLineNumber());
    }

    @Test
    public void testSuppressedExceptions() throws Exception {
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":[{\"message\":\"s1\"},{\"message\":\"s2\"}]}",
                Exception.class);
        assertEquals("main", ex.getMessage());
        assertEquals(2, ex.getSuppressed().length);
        assertEquals("s1", ex.getSuppressed()[0].getMessage());
        assertEquals("s2", ex.getSuppressed()[1].getMessage());
    }

    @Test
    public void testSuppressedBeforeMessage() throws Exception {
        // "suppressed" read before instantiation must be added at the end
        Exception ex = STRICT_MAPPER.readValue(
                "{\"suppressed\":[{\"message\":\"s1\"}],\"message\":\"main\"}",
                Exception.class);
        assertEquals("main", ex.getMessage());
        assertEquals(1, ex.getSuppressed().length);
        assertEquals("s1", ex.getSuppressed()[0].getMessage());
    }

    @Test
    public void testLocalizedMessageIsSkipped() throws Exception {
        // "localizedMessage" is derived, must be skipped without failure
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\",\"localizedMessage\":\"should-not-apply\"}",
                Exception.class);
        assertEquals("boom", ex.getMessage());
        assertEquals("boom", ex.getLocalizedMessage());
    }

    @Test
    public void testPropertyBasedCreator() throws Exception {
        CreatorException ex = STRICT_MAPPER.readValue(
                "{\"message\":\"created\"}", CreatorException.class);
        assertEquals("created", ex.getMessage());
    }

    @Test
    public void testDelegatingCreator() throws Exception {
        DelegateException ex = STRICT_MAPPER.readValue(
                "{\"message\":\"delegated\"}", DelegateException.class);
        assertEquals("delegated", ex.getMessage());
    }

    /*
    /**********************************************************************
    /* Boundary conditions and edge cases
    /**********************************************************************
     */

    @Test
    public void testEmptyObjectGivesThrowableWithoutMessage() throws Exception {
        Exception ex = STRICT_MAPPER.readValue("{}", Exception.class);
        assertNull(ex.getMessage());
    }

    @Test
    public void testMessageWithDefaultConstructorOnly() throws Exception {
        // No single-String creator available: instance created via default
        // constructor, "message" cannot be assigned, but must not fail
        DefaultCtorException ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\"}", DefaultCtorException.class);
        assertNotNull(ex);
        assertNull(ex.getMessage());
    }

    @Test
    public void testNullCauseIsSkipped() throws Exception {
        // [databind#4248]: initCause(null) would throw, so null "cause" must be skipped
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\",\"cause\":null}", Exception.class);
        assertEquals("boom", ex.getMessage());
        assertNull(ex.getCause());
    }

    @Test
    public void testNullStackTraceIsSkipped() throws Exception {
        // setStackTrace(null) throws NPE, so null "stackTrace" must be skipped
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\",\"stackTrace\":null}", Exception.class);
        assertEquals("boom", ex.getMessage());
        assertNotNull(ex.getStackTrace());
    }

    @Test
    public void testNullSuppressedIsSkipped() throws Exception {
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":null}", Exception.class);
        assertEquals("main", ex.getMessage());
        assertEquals(0, ex.getSuppressed().length);
    }

    @Test
    public void testSuppressedNullEntriesAreSkipped() throws Exception {
        // null entries within the suppressed array must not be added
        Exception ex = STRICT_MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":[null,{\"message\":\"s1\"}]}",
                Exception.class);
        assertEquals("main", ex.getMessage());
        assertEquals(1, ex.getSuppressed().length);
        assertEquals("s1", ex.getSuppressed()[0].getMessage());
    }

    /*
    /**********************************************************************
    /* Invalid inputs and error handling
    /**********************************************************************
     */

    @Test(expected = JacksonException.class)
    public void testUnknownPropertyFailsWhenEnabled() throws Exception {
        STRICT_MAPPER.readValue(
                "{\"message\":\"boom\",\"unknownProp\":42}", Exception.class);
    }

    @Test
    public void testUnknownPropertyIgnoredWhenDisabled() throws Exception {
        Exception ex = LENIENT_MAPPER.readValue(
                "{\"message\":\"boom\",\"unknownProp\":42}", Exception.class);
        assertEquals("boom", ex.getMessage());
    }

    @Test
    public void testExplicitlyIgnoredPropertyIsSkipped() throws Exception {
        IgnoringException ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\",\"ignoreMe\":42}", IgnoringException.class);
        assertEquals("boom", ex.getMessage());
    }

    @Test
    public void testIgnoreListDoesNotDropStandardMessage() throws Exception {
        // Standard "message" handling must occur before ignore-list checking
        // (see [databind#6157])
        IgnoreMessageException ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\"}", IgnoreMessageException.class);
        assertEquals("boom", ex.getMessage());
    }

    @Test(expected = JacksonException.class)
    public void testAbstractTypeFails() throws Exception {
        STRICT_MAPPER.readValue("{\"message\":\"boom\"}", AbstractThrowable.class);
    }

    @Test(expected = JacksonException.class)
    public void testNoUsableCreatorFails() throws Exception {
        // Neither a default constructor nor a single-String-arg constructor
        // nor an explicit @JsonCreator: must report missing instantiator
        STRICT_MAPPER.readValue("{\"message\":\"boom\"}", NoCreatorException.class);
    }

    /*
    /**********************************************************************
    /* Dependency interactions (views, any-setter)
    /**********************************************************************
     */

    @Test
    public void testAnySetterCapturesUnknown() throws Exception {
        AnySetterException ex = STRICT_MAPPER.readValue(
                "{\"message\":\"boom\",\"extraProp\":true}", AnySetterException.class);
        assertEquals("boom", ex.getMessage());
        assertEquals(Boolean.TRUE, ex.getExtras().get("extraProp"));
    }

    @Test
    public void testViewIncludedPropertyIsSet() throws Exception {
        ViewedException ex = STRICT_MAPPER.readerFor(ViewedException.class)
                .withView(ViewA.class)
                .readValue("{\"message\":\"boom\",\"code\":7}");
        assertEquals("boom", ex.getMessage());
        assertEquals(7, ex.getCode());
    }

    @Test
    public void testViewExcludedPropertyIsNotSet() throws Exception {
        // "code" is only visible in ViewA; reading with ViewB must leave it unset.
        // "message" has no explicit view and is not restricted ([databind#6190])
        ViewedException ex = STRICT_MAPPER.readerFor(ViewedException.class)
                .withView(ViewB.class)
                .readValue("{\"message\":\"boom\",\"code\":7}");
        assertEquals("boom", ex.getMessage());
        assertEquals(0, ex.getCode());
    }
}