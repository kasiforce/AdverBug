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
        } catch (JacksonException e) {
            // Scalar String input is passed to the property-based creator, which
            // fails to map it to any known label and reports an instantiation problem
            verifyException(e, "Unknown PropFactoryEnum label");
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