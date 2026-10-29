package tools.jackson.databind.deser.jdk;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.Test;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.annotation.JsonAnySetter;
import tools.jackson.databind.annotation.JsonCreator;
import tools.jackson.databind.annotation.JsonIgnoreProperties;
import tools.jackson.databind.annotation.JsonView;
import tools.jackson.databind.exc.InvalidDefinitionException;
import tools.jackson.databind.exc.UnrecognizedPropertyException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Unit tests for {@link ThrowableDeserializer#deserializeFromObject}, covering:
 *<ul>
 * <li>Message-based instantiation (single-String constructor, default constructor)</li>
 * <li>Deferred ("pending") handling of properties that occur before "message"</li>
 * <li>Standard Throwable properties: "cause", "stackTrace", "suppressed",
 *     "localizedMessage"</li>
 * <li>Null-value skipping for "cause" and "stackTrace"</li>
 * <li>View handling, ignorable properties, any-setter and delegate creators</li>
 * <li>Error cases: abstract types and types without usable creators</li>
 *</ul>
 */
public class DeserializeFromObjectTests
{
    private final JsonMapper MAPPER = JsonMapper.builder().build();

    private final JsonMapper STRICT_MAPPER = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    private final JsonMapper LENIENT_MAPPER = JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    /*
    /**********************************************************
    /* Helper types
    /**********************************************************
     */

    @SuppressWarnings("serial")
    public static class CustomThrowable extends RuntimeException {
        public int code;

        public CustomThrowable() { }
        public CustomThrowable(String msg) { super(msg); }
    }

    @SuppressWarnings("serial")
    public static class StringOnlyThrowable extends RuntimeException {
        public StringOnlyThrowable(String msg) { super(msg); }
    }

    @SuppressWarnings("serial")
    public static class NoDefaultThrowable extends RuntimeException {
        public NoDefaultThrowable(int code) { super("code=" + code); }
    }

    public static abstract class AbstractThrowable extends RuntimeException { }

    @SuppressWarnings("serial")
    @JsonIgnoreProperties({ "message", "ignoredProp" })
    public static class IgnoringThrowable extends RuntimeException {
        public IgnoringThrowable() { }
        public IgnoringThrowable(String msg) { super(msg); }
    }

    @SuppressWarnings("serial")
    public static class AnySetterThrowable extends RuntimeException {
        public Map<String, Object> extras = new LinkedHashMap<>();

        public AnySetterThrowable() { }
        public AnySetterThrowable(String msg) { super(msg); }

        @JsonAnySetter
        public void addExtra(String key, Object value) {
            extras.put(key, value);
        }
    }

    @SuppressWarnings("serial")
    public static class DelegateThrowable extends RuntimeException {
        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public DelegateThrowable(Map<String, Object> props) {
            super(String.valueOf(props.get("message")));
        }
    }

    public static class Views {
        static class Public { }
        static class Admin { }
    }

    @SuppressWarnings("serial")
    public static class ViewedThrowable extends RuntimeException {
        public ViewedThrowable() { }
        public ViewedThrowable(String msg) { super(msg); }

        @JsonView(Views.Public.class)
        @Override
        public String getMessage() { return super.getMessage(); }
    }

    /*
    /**********************************************************
    /* Basic functionality
    /**********************************************************
     */

    @Test
    public void testDeserializeExceptionWithMessage() throws Exception {
        Exception ex = MAPPER.readValue("{\"message\":\"boom\"}", Exception.class);
        assertEquals("boom", ex.getMessage());
        assertNull(ex.getCause());
    }

    @Test
    public void testEmptyMessage() throws Exception {
        Exception ex = MAPPER.readValue("{\"message\":\"\"}", Exception.class);
        assertEquals("", ex.getMessage());
    }

    @Test
    public void testMissingMessageInstantiatesWithNullMessage() throws Exception {
        Exception ex = MAPPER.readValue("{}", Exception.class);
        assertNotNull(ex);
        assertNull(ex.getMessage());
        assertNull(ex.getCause());
    }

    @Test
    public void testStdPropertyNameMatchIsCaseInsensitive() throws Exception {
        Exception ex = MAPPER.readValue("{\"Message\":\"cased\"}", Exception.class);
        assertEquals("cased", ex.getMessage());
    }

    @Test
    public void testSingleStringConstructorOnly() throws Exception {
        StringOnlyThrowable ex = MAPPER.readValue(
                "{\"message\":\"from-string\"}", StringOnlyThrowable.class);
        assertEquals("from-string", ex.getMessage());
    }

    /*
    /**********************************************************
    /* "cause" handling (including [databind#4248] null skipping)
    /**********************************************************
     */

    @Test
    public void testCauseBeforeMessageIsDeferred() throws Exception {
        Exception ex = MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}",
                Exception.class);
        assertEquals("outer", ex.getMessage());
        assertNotNull(ex.getCause());
        assertEquals("inner", ex.getCause().getMessage());
    }

    @Test
    public void testCauseAfterMessageAndNestedChain() throws Exception {
        Exception ex = MAPPER.readValue(
                "{\"message\":\"a\",\"cause\":{\"message\":\"b\",\"cause\":{\"message\":\"c\"}}}",
                Exception.class);
        assertEquals("a", ex.getMessage());
        assertEquals("b", ex.getCause().getMessage());
        assertEquals("c", ex.getCause().getCause().getMessage());
    }

    @Test
    public void testNullCauseIsSkipped() throws Exception {
        Exception ex1 = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":null}", Exception.class);
        assertEquals("outer", ex1.getMessage());
        assertNull(ex1.getCause());

        Exception ex2 = MAPPER.readValue(
                "{\"cause\":null,\"message\":\"outer\"}", Exception.class);
        assertEquals("outer", ex2.getMessage());
        assertNull(ex2.getCause());
    }

    /*
    /**********************************************************
    /* "stackTrace" handling
    /**********************************************************
     */

    @Test
    public void testStackTraceDeserialization() throws Exception {
        Exception ex = MAPPER.readValue(
                "{\"message\":\"outer\",\"stackTrace\":"
                + "[{\"className\":\"java.lang.Exception\",\"methodName\":\"run\","
                + "\"fileName\":\"Test.java\",\"lineNumber\":42}]}",
                Exception.class);
        assertEquals("outer", ex.getMessage());
        assertEquals(1, ex.getStackTrace().length);
        assertEquals("run", ex.getStackTrace()[0].getMethodName());
        assertEquals("Test.java", ex.getStackTrace()[0].getFileName());
        assertEquals(42, ex.getStackTrace()[0].getLineNumber());
    }

    @Test
    public void testNullStackTraceIsSkipped() throws Exception {
        Exception ex1 = MAPPER.readValue(
                "{\"message\":\"outer\",\"stackTrace\":null}", Exception.class);
        assertEquals("outer", ex1.getMessage());
        assertNotNull(ex1.getStackTrace());

        Exception ex2 = MAPPER.readValue(
                "{\"stackTrace\":null,\"message\":\"outer\"}", Exception.class);
        assertEquals("outer", ex2.getMessage());
        assertNotNull(ex2.getStackTrace());
    }

    /*
    /**********************************************************
    /* "suppressed" handling
    /**********************************************************
     */

    @Test
    public void testSuppressedExceptions() throws Exception {
        Exception ex = MAPPER.readValue(
                "{\"message\":\"outer\",\"suppressed\":"
                + "[{\"message\":\"s1\"},{\"message\":\"s2\"}]}",
                Exception.class);
        assertEquals("outer", ex.getMessage());
        assertEquals(2, ex.getSuppressed().length);
        assertEquals("s1", ex.getSuppressed()[0].getMessage());
        assertEquals("s2", ex.getSuppressed()[1].getMessage());
    }

    @Test
    public void testSuppressedNullHandling() throws Exception {
        // null entries inside the array are skipped
        Exception ex = MAPPER.readValue(
                "{\"message\":\"outer\",\"suppressed\":[null,{\"message\":\"only\"}]}",
                Exception.class);
        assertEquals(1, ex.getSuppressed().length);
        assertEquals("only", ex.getSuppressed()[0].getMessage());

        // explicit JSON null for the whole array means no suppressed exceptions
        Exception ex2 = MAPPER.readValue(
                "{\"message\":\"outer\",\"suppressed\":null}", Exception.class);
        assertEquals(0, ex2.getSuppressed().length);
    }

    /*
    /**********************************************************
    /* "localizedMessage" and combined pending properties
    /**********************************************************
     */

    @Test
    public void testLocalizedMessageIsSkipped() throws Exception {
        Exception ex = MAPPER.readValue(
                "{\"message\":\"real\",\"localizedMessage\":\"localized\"}",
                Exception.class);
        assertEquals("real", ex.getMessage());
        assertEquals("real", ex.getLocalizedMessage());
    }

    @Test
    public void testMultiplePendingPropertiesBeforeMessage() throws Exception {
        Exception ex = MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},"
                + "\"stackTrace\":[{\"className\":\"A\",\"methodName\":\"m1\",\"lineNumber\":1}],"
                + "\"suppressed\":[{\"message\":\"s\"}],"
                + "\"message\":\"outer\"}",
                Exception.class);
        assertEquals("outer", ex.getMessage());
        assertNotNull(ex.getCause());
        assertEquals("inner", ex.getCause().getMessage());
        assertEquals(1, ex.getStackTrace().length);
        assertEquals("m1", ex.getStackTrace()[0].getMethodName());
        assertEquals(1, ex.getSuppressed().length);
        assertEquals("s", ex.getSuppressed()[0].getMessage());
    }

    /*
    /**********************************************************
    /* Custom (non-standard) properties, before and after "message"
    /**********************************************************
     */

    @Test
    public void testCustomPropertyBeforeAndAfterMessage() throws Exception {
        CustomThrowable ex1 = MAPPER.readValue(
                "{\"message\":\"m\",\"code\":7}", CustomThrowable.class);
        assertEquals("m", ex1.getMessage());
        assertEquals(7, ex1.code);

        CustomThrowable ex2 = MAPPER.readValue(
                "{\"code\":7,\"message\":\"m\"}", CustomThrowable.class);
        assertEquals("m", ex2.getMessage());
        assertEquals(7, ex2.code);
    }

    /*
    /**********************************************************
    /* Creator variants
    /**********************************************************
     */

    @Test
    public void testDelegateCreatorIsUsed() throws Exception {
        DelegateThrowable ex = MAPPER.readValue(
                "{\"message\":\"delegated\",\"code\":3}", DelegateThrowable.class);
        assertEquals("delegated", ex.getMessage());
    }

    /*
    /**********************************************************
    /* Any-setter handling
    /**********************************************************
     */

    @Test
    public void testAnySetterHandling() throws Exception {
        AnySetterThrowable ex = MAPPER.readValue(
                "{\"message\":\"m\",\"extra1\":42}", AnySetterThrowable.class);
        assertEquals("m", ex.getMessage());
        assertEquals(Integer.valueOf(42), ex.extras.get("extra1"));

        // any-setter encountered before "message" triggers instantiation as well
        AnySetterThrowable ex2 = MAPPER.readValue(
                "{\"extra2\":7}", AnySetterThrowable.class);
        assertNull(ex2.getMessage());
        assertEquals(Integer.valueOf(7), ex2.extras.get("extra2"));
    }

    /*
    /**********************************************************
    /* Ignorable properties; standard props must not be dropped
    /* (see [databind#6157])
    /**********************************************************
     */

    @Test
    public void testIgnorablePropsDoNotAffectStandardMessage() throws Exception {
        IgnoringThrowable ex = MAPPER.readValue(
                "{\"message\":\"kept\",\"ignoredProp\":1}", IgnoringThrowable.class);
        assertEquals("kept", ex.getMessage());
    }

    /*
    /**********************************************************
    /* Unknown property handling
    /**********************************************************
     */

    @Test
    public void testUnknownPropertyFailsWhenEnabled() throws Exception {
        try {
            STRICT_MAPPER.readValue(
                    "{\"message\":\"m\",\"bogus\":13}", Exception.class);
            fail("Should not accept unknown property when FAIL_ON_UNKNOWN_PROPERTIES enabled");
        } catch (UnrecognizedPropertyException e) {
            // expected
        }
    }

    @Test
    public void testUnknownPropertyIgnoredWhenDisabled() throws Exception {
        Exception ex = LENIENT_MAPPER.readValue(
                "{\"message\":\"m\",\"bogus\":13}", Exception.class);
        assertEquals("m", ex.getMessage());
    }

    /*
    /**********************************************************
    /* Invalid types / missing creators
    /**********************************************************
     */

    @Test
    public void testAbstractTypeFails() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"m\"}", AbstractThrowable.class);
            fail("Should not instantiate abstract type");
        } catch (InvalidDefinitionException e) {
            // expected: abstract type (need to add/enable type information?)
        }
    }

    @Test
    public void testNoUsableCreatorFails() throws Exception {
        try {
            MAPPER.readValue("{\"message\":\"m\"}", NoDefaultThrowable.class);
            fail("Should not instantiate type without default or single-String constructor");
        } catch (InvalidDefinitionException e) {
            // expected
        }
    }

    /*
    /**********************************************************
    /* View handling (see [databind#6190])
    /**********************************************************
     */

    @Test
    public void testMessageWithMatchingViewIsSet() throws Exception {
        ViewedThrowable ex = MAPPER.readerFor(ViewedThrowable.class)
                .withView(Views.Public.class)
                .readValue("{\"message\":\"visible\"}");
        assertEquals("visible", ex.getMessage());
    }

    @Test
    public void testMessageWithNonMatchingViewIsExcluded() throws Exception {
        ViewedThrowable ex = MAPPER.readerFor(ViewedThrowable.class)
                .withView(Views.Admin.class)
                .readValue("{\"message\":\"hidden\"}");
        assertNull(ex.getMessage());
    }
}