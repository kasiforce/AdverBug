package tools.jackson.databind.deser.jdk;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonView;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.PropertyNamingStrategies;
import tools.jackson.databind.exc.InvalidDefinitionException;
import tools.jackson.databind.exc.UnrecognizedPropertyException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class DeserializeFromObjectTests
{
    private final ObjectMapper MAPPER = JsonMapper.builder().build();

    private final ObjectMapper STRICT_MAPPER = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    private final ObjectMapper LENIENT_MAPPER = JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build();

    /*
    /**********************************************************************
    /* Helper types
    /**********************************************************************
     */

    public static class MyException extends Exception {
        private int code;

        public MyException() { super(); }
        public MyException(String message) { super(message); }

        public int getCode() { return code; }
        public void setCode(int code) { this.code = code; }
    }

    public static class DefaultOnlyException extends Exception {
        public DefaultOnlyException() { super(); }
    }

    public static class NoDefaultException extends Exception {
        public NoDefaultException(int code) { super("code: " + code); }
    }

    public static abstract class AbstractException extends Exception { }

    public static class CreatorException extends Exception {
        private final int code;

        @JsonCreator
        public CreatorException(@JsonProperty("msg") String message,
                @JsonProperty("code") int code) {
            super(message);
            this.code = code;
        }

        public int getCode() { return code; }
    }

    @JsonIgnoreProperties({ "secret" })
    public static class IgnoringException extends Exception {
        public IgnoringException() { super(); }
        public IgnoringException(String message) { super(message); }
    }

    @JsonIgnoreProperties({ "suppressed" })
    public static class IgnoringSuppressedException extends Exception {
        public IgnoringSuppressedException() { super(); }
        public IgnoringSuppressedException(String message) { super(message); }
    }

    public static class AnySetterException extends Exception {
        public final Map<String, Object> extras = new LinkedHashMap<String, Object>();

        public AnySetterException() { super(); }
        public AnySetterException(String message) { super(message); }

        @JsonAnySetter
        public void addExtra(String name, Object value) {
            extras.put(name, value);
        }
    }

    public static class SnakeCaseException extends Exception {
        private String userName;

        public SnakeCaseException() { super(); }
        public SnakeCaseException(String message) { super(message); }

        public String getUserName() { return userName; }
        public void setUserName(String userName) { this.userName = userName; }
    }

    static class Views {
        public static class Included { }
    }

    public static class ViewedException extends Exception {
        @JsonView(Views.Included.class)
        public Integer code;

        public ViewedException() { super(); }
        public ViewedException(String message) { super(message); }
    }

    /*
    /**********************************************************************
    /* Basic functionality
    /**********************************************************************
     */

    @Test
    public void testSimpleMessageDeserialization() throws Exception
    {
        Exception value = MAPPER.readValue("{\"message\":\"Hello, world!\"}", Exception.class);
        assertEquals("Hello, world!", value.getMessage());
    }

    @Test
    public void testEmptyObjectYieldsNullMessage() throws Exception
    {
        Exception value = MAPPER.readValue("{}", Exception.class);
        assertNotNull(value);
        assertNull(value.getMessage());
    }

    @Test
    public void testCauseAfterMessage() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"outer\",\"cause\":{\"message\":\"inner\"}}", Exception.class);
        assertEquals("outer", value.getMessage());
        Throwable cause = value.getCause();
        assertNotNull(cause);
        assertEquals("inner", cause.getMessage());
    }

    @Test
    public void testNestedCauseChain() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"a\",\"cause\":{\"message\":\"b\",\"cause\":{\"message\":\"c\"}}}",
                Exception.class);
        assertEquals("a", value.getMessage());
        assertNotNull(value.getCause());
        assertEquals("b", value.getCause().getMessage());
        assertNotNull(value.getCause().getCause());
        assertEquals("c", value.getCause().getCause().getMessage());
    }

    @Test
    public void testCauseBeforeMessageIsDeferred() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"cause\":{\"message\":\"inner\"},\"message\":\"outer\"}", Exception.class);
        assertEquals("outer", value.getMessage());
        assertNotNull(value.getCause());
        assertEquals("inner", value.getCause().getMessage());
    }

    @Test
    public void testNullCauseIsSkipped() throws Exception
    {
        Exception value = MAPPER.readValue("{\"message\":\"m\",\"cause\":null}", Exception.class);
        assertEquals("m", value.getMessage());
        assertNull(value.getCause());

        Exception value2 = MAPPER.readValue("{\"cause\":null,\"message\":\"m\"}", Exception.class);
        assertEquals("m", value2.getMessage());
        assertNull(value2.getCause());
    }

    @Test
    public void testStackTraceDeserialization() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"m\",\"stackTrace\":[{\"className\":\"com.example.Foo\",\"methodName\":\"bar\",\"fileName\":\"Foo.java\",\"lineNumber\":42}]}",
                Exception.class);
        assertEquals("m", value.getMessage());
        StackTraceElement[] st = value.getStackTrace();
        assertEquals(1, st.length);
        assertEquals("com.example.Foo", st[0].getClassName());
        assertEquals("bar", st[0].getMethodName());
        assertEquals("Foo.java", st[0].getFileName());
        assertEquals(42, st[0].getLineNumber());
    }

    @Test
    public void testNullStackTraceIsSkipped() throws Exception
    {
        Exception value = MAPPER.readValue("{\"message\":\"m\",\"stackTrace\":null}", Exception.class);
        assertEquals("m", value.getMessage());
    }

    @Test
    public void testSuppressedExceptionsDeserialized() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"main\",\"suppressed\":[{\"message\":\"s1\"},{\"message\":\"s2\"}]}",
                Exception.class);
        assertEquals("main", value.getMessage());
        Throwable[] suppressed = value.getSuppressed();
        assertEquals(2, suppressed.length);
        assertEquals("s1", suppressed[0].getMessage());
        assertEquals("s2", suppressed[1].getMessage());
    }

    @Test
    public void testNullSuppressedArray() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":null}", Exception.class);
        assertEquals("m", value.getMessage());
        assertEquals(0, value.getSuppressed().length);
    }

    @Test
    public void testEmptySuppressedArray() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":[]}", Exception.class);
        assertEquals("m", value.getMessage());
        assertEquals(0, value.getSuppressed().length);
    }

    @Test
    public void testSuppressedNullEntriesSkipped() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":[null,{\"message\":\"s\"}]}", Exception.class);
        assertEquals("m", value.getMessage());
        Throwable[] suppressed = value.getSuppressed();
        assertEquals(1, suppressed.length);
        assertEquals("s", suppressed[0].getMessage());
    }

    /*
    /**********************************************************************
    /* Standard Throwable property handling
    /**********************************************************************
     */

    @Test
    public void testLocalizedMessageIgnored() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"message\":\"m\",\"localizedMessage\":\"other\"}", Exception.class);
        assertEquals("m", value.getMessage());
    }

    @Test
    public void testLocalizedMessageOnlyYieldsNullMessage() throws Exception
    {
        Exception value = MAPPER.readValue("{\"localizedMessage\":\"x\"}", Exception.class);
        assertNotNull(value);
        assertNull(value.getMessage());
    }

    @Test
    public void testLocalizedMessageWithStructuredValueSkipped() throws Exception
    {
        Exception value = MAPPER.readValue(
                "{\"localizedMessage\":{\"a\":[1,2]},\"message\":\"m\"}", Exception.class);
        assertEquals("m", value.getMessage());
    }

    @Test
    public void testMessageFromNumberValue() throws Exception
    {
        Exception value = MAPPER.readValue("{\"message\":123}", Exception.class);
        assertEquals("123", value.getMessage());
    }

    @Test
    public void testMessageNameMatchedCaseInsensitively() throws Exception
    {
        Exception value = MAPPER.readValue("{\"Message\":\"Upper\"}", Exception.class);
        assertEquals("Upper", value.getMessage());
    }

    /*
    /**********************************************************************
    /* Regular bean property handling (pending values before "message")
    /**********************************************************************
     */

    @Test
    public void testCustomPropertyBeforeMessageDeferred() throws Exception
    {
        MyException value = MAPPER.readValue(
                "{\"code\":7,\"message\":\"oops\"}", MyException.class);
        assertEquals("oops", value.getMessage());
        assertEquals(7, value.getCode());
    }

    @Test
    public void testCustomPropertyAfterMessageSetDirectly() throws Exception
    {
        MyException value = MAPPER.readValue(
                "{\"message\":\"oops\",\"code\":7}", MyException.class);
        assertEquals("oops", value.getMessage());
        assertEquals(7, value.getCode());
    }

    @Test
    public void testDuplicateCustomPropertyBeforeMessage() throws Exception
    {
        MyException value = MAPPER.readValue(
                "{\"code\":1,\"code\":2,\"message\":\"m\"}", MyException.class);
        assertEquals("m", value.getMessage());
        assertEquals(2, value.getCode());
    }

    /*
    /**********************************************************************
    /* Unknown / ignored / any-setter handling
    /**********************************************************************
     */

    @Test
    public void testUnknownPropertyFailsWhenEnabled() throws Exception
    {
        try {
            STRICT_MAPPER.readValue(
                    "{\"message\":\"m\",\"totallyUnknown\":true}", Exception.class);
            fail("Should not pass with FAIL_ON_UNKNOWN_PROPERTIES enabled");
        } catch (UnrecognizedPropertyException e) {
            assertTrue(e.getMessage().contains("totallyUnknown"));
        }
    }

    @Test
    public void testUnknownPropertyIgnoredWhenDisabled() throws Exception
    {
        Exception value = LENIENT_MAPPER.readValue(
                "{\"message\":\"m\",\"totallyUnknown\":true}", Exception.class);
        assertEquals("m", value.getMessage());
    }

    @Test
    public void testIgnoredPropertySkipped() throws Exception
    {
        IgnoringException value = MAPPER.readValue(
                "{\"message\":\"m\",\"secret\":1}", IgnoringException.class);
        assertEquals("m", value.getMessage());
    }

    @Test
    public void testStandardSuppressedNotDroppedByIgnoreList() throws Exception
    {
        IgnoringSuppressedException value = MAPPER.readValue(
                "{\"message\":\"m\",\"suppressed\":[{\"message\":\"s1\"}]}",
                IgnoringSuppressedException.class);
        assertEquals("m", value.getMessage());
        Throwable[] suppressed = value.getSuppressed();
        assertEquals(1, suppressed.length);
        assertEquals("s1", suppressed[0].getMessage());
    }

    @Test
    public void testAnySetterReceivesUnknownProperties() throws Exception
    {
        AnySetterException value = MAPPER.readValue(
                "{\"message\":\"head\",\"alpha\":3,\"beta\":\"two\"}", AnySetterException.class);
        assertEquals("head", value.getMessage());
        assertEquals(2, value.extras.size());
        assertEquals(Integer.valueOf(3), value.extras.get("alpha"));
        assertEquals("two", value.extras.get("beta"));
    }

    /*
    /**********************************************************************
    /* Creator selection / error handling
    /**********************************************************************
     */

    @Test
    public void testPropertyBasedCreatorUsed() throws Exception
    {
        CreatorException value = MAPPER.readValue(
                "{\"msg\":\"hello\",\"code\":7}", CreatorException.class);
        assertEquals("hello", value.getMessage());
        assertEquals(7, value.getCode());
    }

    @Test
    public void testAbstractExceptionTypeRejected() throws Exception
    {
        try {
            MAPPER.readValue("{\"message\":\"m\"}", AbstractException.class);
            fail("Should have failed on abstract type without type information");
        } catch (InvalidDefinitionException e) {
            assertTrue(e.getMessage().contains("abstract type"));
        }
    }

    @Test
    public void testMissingConstructorsRejected() throws Exception
    {
        try {
            MAPPER.readValue("{\"message\":\"m\"}", NoDefaultException.class);
            fail("Should have failed due to missing default/single-String constructor");
        } catch (InvalidDefinitionException e) {
            assertTrue(e.getMessage().contains("constructor"));
        }
    }

    @Test
    public void testDefaultConstructorOnlyLeavesMessageUnset() throws Exception
    {
        DefaultOnlyException value = MAPPER.readValue(
                "{\"message\":\"ignored\"}", DefaultOnlyException.class);
        assertNotNull(value);
        assertNull(value.getMessage());
    }

    /*
    /**********************************************************************
    /* Configuration interactions
    /**********************************************************************
     */

    @Test
    public void testPropertyNamingStrategyApplied() throws Exception
    {
        ObjectMapper snakeCase = JsonMapper.builder()
                .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                .build();
        SnakeCaseException value = snakeCase.readValue(
                "{\"message\":\"m\",\"user_name\":\"jack\"}", SnakeCaseException.class);
        assertEquals("m", value.getMessage());
        assertEquals("jack", value.getUserName());
    }

    @Test
    public void testPropertyVisibleInViewDeserialized() throws Exception
    {
        ViewedException value = MAPPER.readerFor(ViewedException.class)
                .withView(Views.Included.class)
                .readValue("{\"message\":\"m\",\"code\":5}");
        assertEquals("m", value.getMessage());
        assertEquals(Integer.valueOf(5), value.code);
    }
}