package tools.jackson.databind.deser.jdk;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonView;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

/**
 * Unit tests for {@code ThrowableDeserializer.deserializeFromObject}: covers
 * deserialization of standard Throwable properties ("message", "cause",
 * "stackTrace", "suppressed", "localizedMessage"), ordering of "message"
 * relative to other properties (deferred vs direct assignment), null-value
 * skipping, explicit @JsonView handling of "message", ignorable/unknown
 * property handling, and error cases (abstract types, missing constructors).
 */
public class DeserializeFromObjectTests
{
    private final ObjectMapper MAPPER = JsonMapper.builder().build();

    // Helper for asserting exception message contents
    protected void verifyException(Throwable e, String... matches) {
        String msg = e.getMessage();
        String lmsg = (msg == null) ? "" : msg.toLowerCase();
        for (String match : matches) {
            if (!lmsg.contains(match.toLowerCase())) {
                fail("Expected an exception message containing '" + match
                        + "'; got: '" + msg + "'");
            }
        }
    }

    /*
    /**********************************************************************
    /* Basic functionality, "message" handling
    /**********************************************************************
     */

    @Test
    public void testPlainExceptionWithMessage() throws Exception {
        Exception result = MAPPER.readValue("{\"message\":\"m\"}", Exception.class);
        assertEquals("m", result.getMessage());
    }

    @Test
    public void testEmptyObjectYieldsThrowableWithoutMessage() throws Exception {
        Exception result = MAPPER.readValue("{}", Exception.class);
        assertNull(result.getMessage());
        assertNull(result.getCause());
    }

    @Test
    public void testMessageNameMatchedCaseInsensitively() throws Exception {
        // Standard Throwable property names are matched case-insensitively
        Exception result = MAPPER.readValue("{\"MESSAGE\":\"loud\"}", Exception.class);
        assertEquals("loud", result.getMessage());
    }

    @Test
    public void testSingleStringConstructorOnly() throws Exception {
        ExceptionWithOnlyStringCtor result = MAPPER.readValue(
                "{\"message\":\"via-ctor\"}", ExceptionWithOnlyStringCtor.class);
        assertEquals("via-ctor", result.getMessage());
    }

    @Test
    public void testDefaultConstructorOnlyDropsMessage() throws Exception {
        // No single-String constructor and no "message" setter: value can not be bound
        ExceptionWithOnlyDefaultCtor result = MAPPER.readValue(
                "{\"message\":\"m\"}", ExceptionWithOnlyDefaultCtor.class);
        assertNull(result.getMessage());
    }

    /*
    /**********************************************************************
    /* "cause" handling
    /**********************************************************************
     */

    @Test
    public void testCauseAfterMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":{\"message\":\"inner\"}}", Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getCause());
        assertEquals("inner", result.getCause().getMessage());
    }

    @Test
    public void testCauseBeforeMessage() throws Exception {
        // "cause" before "message" must be deferred and applied after instantiation
        Exception result = MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}", Exception.class);
        assertEquals("outer", result.getMessage());
        assertNotNull(result.getCause());
        assertEquals("inner", result.getCause().getMessage());
    }

    @Test
    public void testNullCauseSkipped() throws Exception {
        // [databind#4248]: null "cause" must not blow up
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"cause\":null}", Exception.class);
        assertEquals("m", result.getMessage());
        assertNull(result.getCause());
    }

    /*
    /**********************************************************************
    /* "stackTrace" handling
    /**********************************************************************
     */

    @Test
    public void testStackTraceAfterMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"stackTrace\":"
                + "[{\"className\":\"com.foo.Bar\",\"methodName\":\"baz\",\"lineNumber\":42}]}",
                Exception.class);
        assertEquals("m", result.getMessage());
        StackTraceElement[] elems = result.getStackTrace();
        assertEquals(1, elems.length);
        assertEquals("com.foo.Bar", elems[0].getClassName());
        assertEquals("baz", elems[0].getMethodName());
        assertEquals(42, elems[0].getLineNumber());
    }

    @Test
    public void testNullStackTraceSkipped() throws Exception {
        // setStackTrace(null) throws NPE, so null values must be skipped
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"stackTrace\":null}", Exception.class);
        assertEquals("m", result.getMessage());
    }

    /*
    /**********************************************************************
    /* "suppressed" handling
    /**********************************************************************
     */

    @Test
    public void testSuppressedAfterMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":"
                + "[{\"message\":\"s1\"},{\"message\":\"s2\"}]}", Exception.class);
        assertEquals("m", result.getMessage());
        Throwable[] supp = result.getSuppressed();
        assertEquals(2, supp.length);
        assertEquals("s1", supp[0].getMessage());
        assertEquals("s2", supp[1].getMessage());
    }

    @Test
    public void testSuppressedBeforeMessage() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"suppressed\":[{\"message\":\"s1\"}],\"message\":\"m\"}", Exception.class);
        assertEquals("m", result.getMessage());
        Throwable[] supp = result.getSuppressed();
        assertEquals(1, supp.length);
        assertEquals("s1", supp[0].getMessage());
    }

    @Test
    public void testSuppressedNullEntriesSkipped() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":[null,{\"message\":\"s1\"}]}",
                Exception.class);
        Throwable[] supp = result.getSuppressed();
        assertEquals(1, supp.length);
        assertEquals("s1", supp[0].getMessage());
    }

    @Test
    public void testNullSuppressedSkipped() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":null}", Exception.class);
        assertEquals("m", result.getMessage());
        assertEquals(0, result.getSuppressed().length);
    }

    /*
    /**********************************************************************
    /* Custom properties, deferred vs direct assignment
    /**********************************************************************
     */

    @Test
    public void testCustomPropertyAfterMessage() throws Exception {
        ExceptionWithCode result = MAPPER.readValue(
                "{\"message\":\"hi\",\"code\":3}", ExceptionWithCode.class);
        assertEquals("hi", result.getMessage());
        assertEquals(3, result.getCode());
    }

    @Test
    public void testCustomPropertyBeforeMessage() throws Exception {
        // Property before "message" is deferred, then applied after instantiation
        ExceptionWithCode result = MAPPER.readValue(
                "{\"code\":3,\"message\":\"hi\"}", ExceptionWithCode.class);
        assertEquals("hi", result.getMessage());
        assertEquals(3, result.getCode());
    }

    @Test
    public void testLocalizedMessageIgnored() throws Exception {
        Exception result = MAPPER.readValue(
                "{\"message\":\"m\",\"localizedMessage\":\"localized\"}", Exception.class);
        assertEquals("m", result.getMessage());
    }

    /*
    /**********************************************************************
    /* Unknown, ignorable and any-setter properties
    /**********************************************************************
     */

    @Test
    public void testUnknownPropertyFailsWhenStrict() throws Exception {
        ObjectMapper strictMapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        try {
            strictMapper.readValue("{\"message\":\"m\",\"bogus\":true}", Exception.class);
            fail("Should have failed on unknown property");
        } catch (JacksonException e) {
            verifyException(e, "bogus");
        }
    }

    @Test
    public void testUnknownPropertyIgnoredWhenLenient() throws Exception {
        ObjectMapper lenientMapper = JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        Exception result = lenientMapper.readValue(
                "{\"message\":\"m\",\"bogus\":true}", Exception.class);
        assertEquals("m", result.getMessage());
    }

    @Test
    public void testIgnorablePropertySkipped() throws Exception {
        ObjectMapper strictMapper = JsonMapper.builder()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        ExceptionWithIgnorable result = strictMapper.readValue(
                "{\"message\":\"m\",\"bogus\":42}", ExceptionWithIgnorable.class);
        assertEquals("m", result.getMessage());
    }

    @Test
    public void testAnySetterHandlesUnknownProperties() throws Exception {
        ExceptionWithAnySetter result = MAPPER.readValue(
                "{\"message\":\"m\",\"foo\":42,\"bar\":\"baz\"}", ExceptionWithAnySetter.class);
        assertEquals("m", result.getMessage());
        assertEquals(Integer.valueOf(42), result.getExtras().get("foo"));
        assertEquals("baz", result.getExtras().get("bar"));
    }

    /*
    /**********************************************************************
    /* Error cases
    /**********************************************************************
     */

    @Test
    public void testAbstractTypeFails() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"m\"}", AbstractThrowableSubtype.class);
            fail("Should have failed for abstract type");
        } catch (JacksonException e) {
            verifyException(e, "abstract");
        }
    }

    @Test
    public void testMissingConstructorsFail() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"m\"}", ExceptionWithoutUsableConstructors.class);
            fail("Should have failed without usable constructors");
        } catch (JacksonException e) {
            verifyException(e, "constructor");
        }
    }

    /*
    /**********************************************************************
    /* View handling for "message" ([databind#6190])
    /**********************************************************************
     */

    @Test
    public void testMessageWithExplicitView() throws Exception {
        // Under the explicitly annotated view, "message" is visible
        ExceptionWithViewMessage inView = MAPPER.readerWithView(MyView.class)
                .forType(ExceptionWithViewMessage.class)
                .readValue("{\"message\":\"visible\"}");
        assertEquals("visible", inView.getMessage());

        // Without an active view nothing is excluded
        ExceptionWithViewMessage noView = MAPPER.readValue("{\"message\":\"plain\"}",
                ExceptionWithViewMessage.class);
        assertEquals("plain", noView.getMessage());

        // Under an unrelated view, "message" must be excluded
        ExceptionWithViewMessage otherView = MAPPER.readerWithView(OtherView.class)
                .forType(ExceptionWithViewMessage.class)
                .readValue("{\"message\":\"hidden\"}");
        assertNull(otherView.getMessage());
    }

    /*
    /**********************************************************************
    /* Helper classes
    /**********************************************************************
     */

    static class ExceptionWithCode extends Exception {
        protected int code;

        public ExceptionWithCode() { }
        public ExceptionWithCode(String message) { super(message); }

        public int getCode() { return code; }
        public void setCode(int code) { this.code = code; }
    }

    static class ExceptionWithOnlyStringCtor extends Exception {
        public ExceptionWithOnlyStringCtor(String message) { super(message); }
    }

    static class ExceptionWithOnlyDefaultCtor extends Exception {
        public ExceptionWithOnlyDefaultCtor() { }
    }

    static class ExceptionWithoutUsableConstructors extends Exception {
        public ExceptionWithoutUsableConstructors(String message, int code) {
            super(message);
        }
    }

    abstract static class AbstractThrowableSubtype extends Exception { }

    @JsonIgnoreProperties({ "bogus" })
    static class ExceptionWithIgnorable extends Exception {
        public ExceptionWithIgnorable() { }
        public ExceptionWithIgnorable(String message) { super(message); }
    }

    static class ExceptionWithAnySetter extends Exception {
        protected Map<String, Object> extras = new LinkedHashMap<String, Object>();

        public ExceptionWithAnySetter() { }
        public ExceptionWithAnySetter(String message) { super(message); }

        @JsonAnySetter
        void addExtra(String key, Object value) { extras.put(key, value); }

        public Map<String, Object> getExtras() { return extras; }
    }

    static class ExceptionWithViewMessage extends Exception {
        public ExceptionWithViewMessage() { }
        public ExceptionWithViewMessage(String message) { super(message); }

        @JsonView(MyView.class)
        @Override
        public String getMessage() { return super.getMessage(); }
    }

    static class MyView { }

    static class OtherView { }
}