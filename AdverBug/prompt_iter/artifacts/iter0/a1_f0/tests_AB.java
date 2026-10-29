package tools.jackson.databind.deser.jdk;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;
import com.fasterxml.jackson.annotation.JsonProperty;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.fail;

/**
 * Tests for {@link FactoryBasedEnumDeserializer}, exercised through the public
 * {@link JsonMapper} API using enums with {@code @JsonCreator} static factory
 * methods. Covers delegating String creators, non-String delegating creators
 * (which delegate to a value deserializer first), property-based creators,
 * unknown-value handling (as-null / as-default), rejection of unexpected
 * structured input, and single-value array unwrapping.
 */
public class DeserializeTests
{
    ////////////////////////////////////////////////////////////////////
    // Helper types
    ////////////////////////////////////////////////////////////////////

    public enum DelegatingEnum {
        A, B;

        @JsonCreator
        public static DelegatingEnum fromString(String value) {
            if ("A".equals(value)) {
                return A;
            }
            if ("B".equals(value)) {
                return B;
            }
            throw new IllegalArgumentException("No matching DelegatingEnum for value '" + value + "'");
        }
    }

    public enum IntDelegatingEnum {
        ONE(1), TWO(2);

        private final int code;

        IntDelegatingEnum(int code) {
            this.code = code;
        }

        @JsonCreator
        public static IntDelegatingEnum fromCode(int code) {
            for (IntDelegatingEnum e : values()) {
                if (e.code == code) {
                    return e;
                }
            }
            throw new IllegalArgumentException("No matching IntDelegatingEnum for code " + code);
        }
    }

    public enum PropertyBasedEnum {
        FOO(1), BAR(2);

        private final int code;

        PropertyBasedEnum(int code) {
            this.code = code;
        }

        @JsonCreator
        public static PropertyBasedEnum fromCode(@JsonProperty("code") int code) {
            for (PropertyBasedEnum e : values()) {
                if (e.code == code) {
                    return e;
                }
            }
            throw new IllegalArgumentException("No matching PropertyBasedEnum for code " + code);
        }
    }

    public enum DefaultedEnum {
        A, B,
        @JsonEnumDefaultValue
        OTHER;

        @JsonCreator
        public static DefaultedEnum fromString(String value) {
            if ("A".equals(value)) {
                return A;
            }
            if ("B".equals(value)) {
                return B;
            }
            throw new IllegalArgumentException("No matching DefaultedEnum for value '" + value + "'");
        }
    }

    ////////////////////////////////////////////////////////////////////
    // Tests
    ////////////////////////////////////////////////////////////////////

    // Basic functionality: known values resolved through the factory method.
    @Test
    public void testDelegatingStringCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertSame(DelegatingEnum.A, mapper.readValue("\"A\"", DelegatingEnum.class));
        assertSame(DelegatingEnum.B, mapper.readValue("\"B\"", DelegatingEnum.class));
    }

    // Unknown value without lenient features: factory throws
    // IllegalArgumentException, which must be reported as an exception.
    @Test
    public void testDelegatingCreatorUnknownValueFails() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("\"ZZZ\"", DelegatingEnum.class);
            fail("Expected an exception for unknown enum value");
        } catch (JacksonException e) {
            // expected: creator failure -> handleInstantiationProblem
        }
    }

    // READ_UNKNOWN_ENUM_VALUES_AS_NULL maps unknown values to null,
    // but must not affect known values.
    @Test
    public void testDelegatingCreatorUnknownAsNull() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        assertNull(mapper.readValue("\"ZZZ\"", DelegatingEnum.class));
        assertSame(DelegatingEnum.A, mapper.readValue("\"A\"", DelegatingEnum.class));
    }

    // READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE maps unknown values to
    // the @JsonEnumDefaultValue-annotated constant.
    @Test
    public void testDelegatingCreatorUnknownAsDefault() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        assertSame(DefaultedEnum.OTHER, mapper.readValue("\"ZZZ\"", DefaultedEnum.class));
        assertSame(DefaultedEnum.B, mapper.readValue("\"B\"", DefaultedEnum.class));
    }

    // When both features are enabled, unknown-as-null takes precedence
    // over unknown-as-default.
    @Test
    public void testUnknownWithBothFeaturesPrefersNull() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        assertNull(mapper.readValue("\"ZZZ\"", DefaultedEnum.class));
    }

    // Unknown-as-default without any default constant must still fail.
    @Test
    public void testUnknownAsDefaultWithoutDefaultConstantFails() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        try {
            mapper.readValue("\"ZZZ\"", DelegatingEnum.class);
            fail("Expected an exception when no default enum constant exists");
        } catch (JacksonException e) {
            // expected: _defaultValue is null -> handleInstantiationProblem
        }
    }

    // Non-String delegating creator: token value is first deserialized with
    // the matching value deserializer, then passed to the factory method.
    @Test
    public void testNonStringDelegatingCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertSame(IntDelegatingEnum.ONE, mapper.readValue("1", IntDelegatingEnum.class));
        assertSame(IntDelegatingEnum.TWO, mapper.readValue("2", IntDelegatingEnum.class));
    }

    // Array input without single-value unwrapping is rejected (non-scalar token).
    @Test
    public void testDelegatingCreatorFailsForArrayInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("[\"A\"]", DelegatingEnum.class);
            fail("Expected an exception for array input without single-value unwrapping");
        } catch (JacksonException e) {
            // expected: delegating creator expects a scalar value
        }
    }

    // Object input for a delegating creator: no scalar can be extracted from
    // a plain JSON Object, so an exception is reported.
    @Test
    public void testDelegatingCreatorFailsForObjectInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("{\"value\":\"A\"}", DelegatingEnum.class);
            fail("Expected an exception for Object input with delegating creator");
        } catch (JacksonException e) {
            // expected: unexpected token for scalar extraction
        }
    }

    // Single-element arrays are unwrapped when UNWRAP_SINGLE_VALUE_ARRAYS is on.
    @Test
    public void testUnwrapSingleValueArray() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        assertSame(DelegatingEnum.A, mapper.readValue("[\"A\"]", DelegatingEnum.class));
    }

    // Arrays with more than one value must still fail even when unwrapping
    // is enabled (missing END_ARRAY after the single value).
    @Test
    public void testUnwrapSingleValueArrayFailsForMultipleValues() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        try {
            mapper.readValue("[\"A\", \"B\"]", DelegatingEnum.class);
            fail("Expected an exception when array contains more than one value");
        } catch (JacksonException e) {
            // expected: handleMissingEndArrayForSingle
        }
    }

    // Property-based creator: enum is built from JSON Object properties.
    @Test
    public void testPropertyBasedCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertSame(PropertyBasedEnum.FOO, mapper.readValue("{\"code\":1}", PropertyBasedEnum.class));
        assertSame(PropertyBasedEnum.BAR, mapper.readValue("{\"code\":2}", PropertyBasedEnum.class));
    }

    // Property-based creator whose instantiator cannot create from String
    // must reject non-Object input.
    @Test
    public void testPropertyBasedCreatorFailsForNonObjectInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("\"FOO\"", PropertyBasedEnum.class);
            fail("Expected an exception for non-Object input with property-based creator");
        } catch (JacksonException e) {
            // expected: properties-based creator expects Object value
        }
    }
}

package tools.jackson.databind.deser.jdk;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;
import com.fasterxml.jackson.annotation.JsonProperty;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.exc.MismatchedInputException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

public class DeserializeTests
{
    // Enum with a delegating String-based @JsonCreator factory method
    enum SimpleFactoryEnum {
        A, B, C;

        @JsonCreator
        public static SimpleFactoryEnum fromString(String value) {
            try {
                return valueOf(value);
            } catch (IllegalArgumentException e) {
                throw new IllegalArgumentException(
                        "Unknown SimpleFactoryEnum value: " + value);
            }
        }
    }

    // Enum with a delegating non-String (Integer) @JsonCreator factory method
    enum IntFactoryEnum {
        ONE(1), TWO(2), THREE(3);

        final int code;

        IntFactoryEnum(int code) { this.code = code; }

        @JsonCreator
        public static IntFactoryEnum fromCode(Integer code) {
            for (IntFactoryEnum e : values()) {
                if (e.code == code) {
                    return e;
                }
            }
            throw new IllegalArgumentException("Unknown IntFactoryEnum code: " + code);
        }
    }

    // Enum with a property-based @JsonCreator factory method
    enum PropFactoryEnum {
        X("x"), Y("y");

        final String label;

        PropFactoryEnum(String label) { this.label = label; }

        @JsonCreator
        public static PropFactoryEnum fromProps(@JsonProperty("label") String label) {
            for (PropFactoryEnum e : values()) {
                if (e.label.equals(label)) {
                    return e;
                }
            }
            throw new IllegalArgumentException("Unknown PropFactoryEnum label: " + label);
        }
    }

    // Enum with delegating creator plus a default value for unknown input
    enum DefaultedFactoryEnum {
        A, B,
        @JsonEnumDefaultValue
        UNKNOWN;

        @JsonCreator
        public static DefaultedFactoryEnum fromString(String value) {
            try {
                return valueOf(value);
            } catch (IllegalArgumentException e) {
                throw new IllegalArgumentException(
                        "Unknown DefaultedFactoryEnum value: " + value);
            }
        }
    }

    // Enum with a zero-args @JsonCreator factory method
    enum ZeroArgFactoryEnum {
        SINGLETON;

        @JsonCreator
        public static ZeroArgFactoryEnum create() {
            return SINGLETON;
        }
    }

    protected void verifyException(Throwable e, String... matches) {
        String msg = e.getMessage();
        if (msg == null) {
            msg = "";
        }
        String lmsg = msg.toLowerCase();
        for (String match : matches) {
            if (!lmsg.contains(match.toLowerCase())) {
                fail("Expected exception message containing '" + match
                        + "' but got: '" + msg + "'");
            }
        }
    }

    @Test
    public void testDelegatingStringCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertEquals(SimpleFactoryEnum.A,
                mapper.readValue("\"A\"", SimpleFactoryEnum.class));
        assertEquals(SimpleFactoryEnum.C,
                mapper.readValue("\"C\"", SimpleFactoryEnum.class));
    }

    @Test
    public void testDelegatingCreatorRejectsArrayInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("[\"A\"]", SimpleFactoryEnum.class);
            fail("Should not accept Array input without UNWRAP_SINGLE_VALUE_ARRAYS");
        } catch (MismatchedInputException e) {
            verifyException(e, "Input mismatch reading Enum");
        }
    }

    @Test
    public void testUnwrapSingleValueArray() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        assertEquals(SimpleFactoryEnum.B,
                mapper.readValue("[\"B\"]", SimpleFactoryEnum.class));
    }

    @Test
    public void testUnknownValueAsNull() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        assertNull(mapper.readValue("\"nope\"", SimpleFactoryEnum.class));
    }

    @Test
    public void testUnknownValueUsingDefaultValue() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        assertEquals(DefaultedFactoryEnum.UNKNOWN,
                mapper.readValue("\"nope\"", DefaultedFactoryEnum.class));
    }

    @Test
    public void testUnknownValueFailsByDefault() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("\"nope\"", SimpleFactoryEnum.class);
            fail("Should not accept unknown enum value by default");
        } catch (JacksonException e) {
            // expected: instantiation problem reported for the unknown value
        }
    }

    @Test
    public void testDelegatingNonStringCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertEquals(IntFactoryEnum.ONE, mapper.readValue("1", IntFactoryEnum.class));
        assertEquals(IntFactoryEnum.TWO, mapper.readValue("2", IntFactoryEnum.class));
    }

    @Test
    public void testDelegatingNonStringCreatorUnknownValue() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("99", IntFactoryEnum.class);
            fail("Should not accept unknown enum code by default");
        } catch (JacksonException e) {
            // expected: instantiation problem reported for the unknown code
        }
    }

    @Test
    public void testPropertyBasedCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertEquals(PropFactoryEnum.X,
                mapper.readValue("{\"label\":\"x\"}", PropFactoryEnum.class));
        assertEquals(PropFactoryEnum.Y,
                mapper.readValue("{\"label\":\"y\"}", PropFactoryEnum.class));
    }

    @Test
    public void testPropertyBasedCreatorRejectsStringInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("\"X\"", PropFactoryEnum.class);
            fail("Should not accept String input for properties-based creator");
        } catch (MismatchedInputException e) {
            verifyException(e, "Input mismatch reading Enum");
        }
    }

    @Test
    public void testPropertyBasedCreatorRejectsArrayInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("[{\"label\":\"x\"}]", PropFactoryEnum.class);
            fail("Should not accept Array input for properties-based creator");
        } catch (MismatchedInputException e) {
            verifyException(e, "Input mismatch reading Enum");
        }
    }

    @Test
    public void testZeroArgsFactoryCreator() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        assertEquals(ZeroArgFactoryEnum.SINGLETON,
                mapper.readValue("\"not-an-enum-name\"", ZeroArgFactoryEnum.class));
    }
}