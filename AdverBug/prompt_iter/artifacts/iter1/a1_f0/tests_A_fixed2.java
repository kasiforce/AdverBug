package tools.jackson.databind.deser.jdk;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;
import com.fasterxml.jackson.annotation.JsonProperty;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper;

public class DeserializeTests {

    // Enum with a single-String-argument delegating factory creator
    enum SimpleEnum {
        A, B, C;

        @JsonCreator
        public static SimpleEnum fromString(String value) {
            return SimpleEnum.valueOf(value);
        }
    }

    // Enum with a delegating factory creator taking a non-String (int) argument
    enum CodeEnum {
        CODE_0(0), CODE_1(1), CODE_2(2);

        private final int code;

        private CodeEnum(int code) { this.code = code; }

        public int code() { return code; }

        @JsonCreator
        public static CodeEnum fromCode(int code) {
            for (CodeEnum e : values()) {
                if (e.code == code) {
                    return e;
                }
            }
            throw new IllegalArgumentException("Unknown code: " + code);
        }
    }

    // Enum with a zero-argument factory creator
    enum ZeroArgEnum {
        FALLBACK;

        @JsonCreator
        public static ZeroArgEnum create() {
            return ZeroArgEnum.FALLBACK;
        }
    }

    // Enum with a properties-based creator (multiple @JsonProperty arguments)
    enum PropEnum {
        RED("red", 1),
        BLUE("blue", 2);

        private final String label;
        private final int code;

        private PropEnum(String label, int code) {
            this.label = label;
            this.code = code;
        }

        public String label() { return label; }

        public int code() { return code; }

        @JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
        public static PropEnum fromProperties(@JsonProperty("label") String label,
                @JsonProperty("code") int code) {
            for (PropEnum e : values()) {
                if (e.label.equals(label) && e.code == code) {
                    return e;
                }
            }
            throw new IllegalArgumentException("Unknown PropEnum: " + label + "/" + code);
        }
    }

    // Enum with a delegating creator plus a default value for unknown inputs
    enum DefaultableEnum {
        A("a"),
        B("b"),
        @JsonEnumDefaultValue
        UNKNOWN("unknown");

        private final String key;

        private DefaultableEnum(String key) { this.key = key; }

        public String key() { return key; }

        @JsonCreator
        public static DefaultableEnum fromKey(String key) {
            for (DefaultableEnum e : values()) {
                if (e.key.equals(key) || e.name().equals(key)) {
                    return e;
                }
            }
            throw new IllegalArgumentException("Unknown key: " + key);
        }
    }

    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test
    public void testDelegatingStringCreatorWithValidValues() throws Exception {
        assertEquals(SimpleEnum.A, mapper.readValue("\"A\"", SimpleEnum.class));
        assertEquals(SimpleEnum.B, mapper.readValue("\"B\"", SimpleEnum.class));
        assertEquals(SimpleEnum.C, mapper.readValue("\"C\"", SimpleEnum.class));
    }

    @Test
    public void testDelegatingStringCreatorUsesFactoryMapping() throws Exception {
        // "a" (lowercase) is only resolvable through the factory method, not by name
        assertEquals(DefaultableEnum.A, mapper.readValue("\"a\"", DefaultableEnum.class));
        assertEquals(DefaultableEnum.B, mapper.readValue("\"b\"", DefaultableEnum.class));
    }

    @Test
    public void testDelegatingStringCreatorUnknownValueFails() throws Exception {
        try {
            mapper.readValue("\"NOPE\"", SimpleEnum.class);
            fail("Should have failed on unknown enum value");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testDelegatingStringCreatorObjectInputFails() throws Exception {
        try {
            mapper.readValue("{\"label\":\"A\"}", SimpleEnum.class);
            fail("Should have failed on JSON Object input for delegating String creator");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testArrayInputWithoutUnwrapFeatureFails() throws Exception {
        try {
            mapper.readValue("[\"B\"]", SimpleEnum.class);
            fail("Should have failed on array input without UNWRAP_SINGLE_VALUE_ARRAYS");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testUnknownEnumValueAsNullWhenFeatureEnabled() throws Exception {
        JsonMapper m = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        assertNull(m.readValue("\"nope\"", SimpleEnum.class));
        assertNull(m.readValue("\"nope\"", DefaultableEnum.class));
    }

    @Test
    public void testUnknownEnumValueAsDefaultWhenFeatureEnabled() throws Exception {
        JsonMapper m = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        assertEquals(DefaultableEnum.UNKNOWN, m.readValue("\"zzz\"", DefaultableEnum.class));
    }

    @Test
    public void testUnknownEnumValueWithoutDefaultFeatureFails() throws Exception {
        try {
            mapper.readValue("\"zzz\"", DefaultableEnum.class);
            fail("Should have failed on unknown enum key without lenient features enabled");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testIntFactoryCreatorWithValidCodes() throws Exception {
        assertEquals(CodeEnum.CODE_0, mapper.readValue("0", CodeEnum.class));
        assertEquals(CodeEnum.CODE_1, mapper.readValue("1", CodeEnum.class));
        assertEquals(CodeEnum.CODE_2, mapper.readValue("2", CodeEnum.class));
    }

    @Test
    public void testIntFactoryCreatorWithUnknownCodeFails() throws Exception {
        try {
            mapper.readValue("99", CodeEnum.class);
            fail("Should have failed on unknown enum code");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testZeroArgFactorySkipsAnyJsonInput() throws Exception {
        assertEquals(ZeroArgEnum.FALLBACK, mapper.readValue("{\"ignored\":[1,2,3]}", ZeroArgEnum.class));
        assertEquals(ZeroArgEnum.FALLBACK, mapper.readValue("[1,2,3]", ZeroArgEnum.class));
        assertEquals(ZeroArgEnum.FALLBACK, mapper.readValue("\"ignored\"", ZeroArgEnum.class));
        assertEquals(ZeroArgEnum.FALLBACK, mapper.readValue("{}", ZeroArgEnum.class));
    }

    @Test
    public void testPropertiesBasedCreatorWithObjectInput() throws Exception {
        assertEquals(PropEnum.RED, mapper.readValue("{\"label\":\"red\",\"code\":1}", PropEnum.class));
        assertEquals(PropEnum.BLUE, mapper.readValue("{\"label\":\"blue\",\"code\":2}", PropEnum.class));
    }

    @Test
    public void testPropertiesBasedCreatorWithScalarInputFails() throws Exception {
        try {
            mapper.readValue("\"red\"", PropEnum.class);
            fail("Should have failed on scalar input for properties-based creator");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testPropertiesBasedCreatorWithMissingPropertyFails() throws Exception {
        try {
            mapper.readValue("{\"label\":\"red\"}", PropEnum.class);
            fail("Should have failed when a creator property is missing");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testUnwrapSingleValueArrayWithDelegatingCreator() throws Exception {
        JsonMapper m = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        assertEquals(SimpleEnum.B, m.readValue("[\"B\"]", SimpleEnum.class));
    }

    @Test
    public void testUnwrapSingleValueArrayWithMultipleElementsFails() throws Exception {
        JsonMapper m = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        try {
            m.readValue("[\"B\", \"C\"]", SimpleEnum.class);
            fail("Should have failed on multi-element array with UNWRAP_SINGLE_VALUE_ARRAYS");
        } catch (JacksonException e) {
            // expected
        }
    }
}