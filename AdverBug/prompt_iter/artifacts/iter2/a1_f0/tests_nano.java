package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;

public class DeserializeTests {

    @Test
    public void testDeserializeEnumFromJsonCreator_basic() throws Exception {
        ObjectMapper mapper = JsonMapper.builder().build();
        Color color = mapper.readValue("\"red\"", Color.class);
        assertEquals(Color.RED, color);
    }

    @Test
    public void testDeserializeEnumUnknownValue_returnsNullWhenFeatureEnabled() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(tools.jackson.databind.cfg.EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        Color color = mapper.readValue("\"purple\"", Color.class);
        assertNull(color);
    }

    @Test
    public void testDeserializeEnumUnknownValue_usesDefaultWhenConfigured() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(tools.jackson.databind.cfg.EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        Color color = mapper.readValue("\"purple\"", Color.class);
        assertEquals(Color.UNKNOWN, color);
    }

    @Test
    public void testDeserializeEnumFromJsonCreator_withUnwrappedSingleValueArray() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        Color color = mapper.readValue("[\"red\"]", Color.class);
        assertEquals(Color.RED, color);
    }

    @Test
    public void testDeserializeEnumFromJsonCreator_invalidInputThrows() throws Exception {
        ObjectMapper mapper = JsonMapper.builder().build();
        try {
            mapper.readValue("1", Color.class);
            fail("Expected an exception for invalid enum value input");
        } catch (Exception e) {
            // expected
        }
    }
}

enum Color {
    RED,
    GREEN,
    BLUE,
    @JsonEnumDefaultValue
    UNKNOWN;

    @JsonCreator
    public static Color fromString(String s) {
        return Color.valueOf(s.toUpperCase());
    }
}