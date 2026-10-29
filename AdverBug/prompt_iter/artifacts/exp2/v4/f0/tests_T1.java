package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationContext;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;
import tools.jackson.databind.json.JsonMapper;

public class DeserializeTests {

    // Enum with a delegating factory method
    public enum DelegatingEnum {
        RED("red"),
        GREEN("green"),
        @JsonEnumDefaultValue
        DEFAULT("default");

        private final String code;

        DelegatingEnum(String code) {
            this.code = code;
        }

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static DelegatingEnum fromCode(String code) {
            for (DelegatingEnum e : values()) {
                if (e.code.equals(code)) {
                    return e;
                }
            }
            throw new IllegalArgumentException("Unknown: " + code);
        }
    }

    @Test
    public void testDelegatingEnumDeserializationFromString() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        DelegatingEnum actual = mapper.readValue("\"red\"", DelegatingEnum.class);
        assertEquals(DelegatingEnum.RED, actual);
    }

    @Test
    public void testUnknownEnumValueUsesDefaultValue() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        DelegatingEnum actual = mapper.readValue("\"unknown\"", DelegatingEnum.class);
        assertEquals(DelegatingEnum.DEFAULT, actual);
    }

    @Test
    public void testUnknownEnumValueReturnsNullWhenConfigured() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        DelegatingEnum actual = mapper.readValue("\"unknown\"", DelegatingEnum.class);
        assertNull(actual);
    }

    @Test
    public void testUnwrapSingleValueArrayDeserialization() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        DelegatingEnum actual = mapper.readValue("[\"green\"]", DelegatingEnum.class);
        assertEquals(DelegatingEnum.GREEN, actual);
    }

    @Test
    public void testInputMismatchForNullInput() throws Exception {
        JsonMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("null", DelegatingEnum.class);
            fail("Expected JacksonException");
        } catch (JacksonException e) {
            // expected
        }
    }
}