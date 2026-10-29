package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;
import tools.jackson.databind.json.JsonMapper;

public class DeserializeTests {

    // 1) Delegating string-based factory
    public static enum DelegatingStringEnum {
        RED, BLUE;

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static DelegatingStringEnum fromValue(String code) {
            if ("R".equals(code)) {
                return RED;
            } else if ("B".equals(code)) {
                return BLUE;
            }
            throw new IllegalArgumentException("Unknown code: " + code);
        }
    }

    // 2) Delegating int-based factory
    public static enum DelegatingIntEnum {
        ONE(1), TWO(2);
        private final int code;
        DelegatingIntEnum(int c) { this.code = c; }

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static DelegatingIntEnum fromValue(Integer code) {
            if (code != null) {
                switch (code) {
                    case 1: return ONE;
                    case 2: return TWO;
                    default: break;
                }
            }
            throw new IllegalArgumentException("Unknown code: " + code);
        }
    }

    // 3) For unwrapping single-value arrays
    // Reuse DelegatingStringEnum with unwrap feature enabled on mapper.

    // 4) Unknown value returns null when configured to do so
    public static enum UnknownNullEnum {
        A, B;

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static UnknownNullEnum fromValue(String s) {
            if ("A".equals(s)) return A;
            if ("B".equals(s)) return B;
            throw new IllegalArgumentException("Unknown: " + s);
        }
    }

    // 5) Default value for unknown values
    public static enum DefaultEnum {
        A, B,
        @JsonEnumDefaultValue
        C;
        // no factory needed; default value used when unknown value encountered
    }

    // 6) Zero-arg factory path
    public static enum ZeroArgEnum {
        VALUE;

        @JsonCreator
        public static ZeroArgEnum create() { return VALUE; }
    }

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testDelegatingStringEnumBasic() throws Exception {
        String json = "\"R\"";
        DelegatingStringEnum v = MAPPER.readValue(json, DelegatingStringEnum.class);
        assertEquals(DelegatingStringEnum.RED, v);
    }

    @Test
    public void testDelegatingIntEnumBasic() throws Exception {
        String json = "1";
        DelegatingIntEnum v = MAPPER.readValue(json, DelegatingIntEnum.class);
        assertEquals(DelegatingIntEnum.ONE, v);
    }

    @Test
    public void testUnwrapSingleValueArrayWithDelegatingStringEnum() throws Exception {
        // Enable unwrap-single-value array feature
        ObjectMapper m = JsonMapper.builder()
                .enable(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS)
                .build();
        String json = "[\"R\"]";
        DelegatingStringEnum v = m.readValue(json, DelegatingStringEnum.class);
        assertEquals(DelegatingStringEnum.RED, v);
    }

    @Test
    public void testUnknownValueAsNullWhenConfigured() throws Exception {
        ObjectMapper m = JsonMapper.builder()
                .enable(tools.jackson.databind.cfg.EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        String json = "\"Z\"";
        UnknownNullEnum v = m.readValue(json, UnknownNullEnum.class);
        assertNull(v);
    }

    @Test
    public void testUnknownValueUsesDefaultWhenConfigured() throws Exception {
        ObjectMapper m = JsonMapper.builder()
                .enable(tools.jackson.databind.cfg.EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)
                .build();
        String json = "\"X\"";
        DefaultEnum v = m.readValue(json, DefaultEnum.class);
        // Should map to the JsonEnumDefaultValue annotated constant
        assertEquals(DefaultEnum.C, v);
    }

    @Test
    public void testZeroArgFactoryPath() throws Exception {
        String json = "\"anything\"";
        ZeroArgEnum v = MAPPER.readValue(json, ZeroArgEnum.class);
        assertEquals(ZeroArgEnum.VALUE, v);
    }

    @Test
    public void testInvalidInputTypeForStringPathThrows() {
        ObjectMapper m = JsonMapper.builder().build();
        String json = "{}"; // START_OBJECTToken is invalid for a string-based delegating creator
        try {
            m.readValue(json, DelegatingStringEnum.class);
            fail("Expected exception due to input mismatch for string-based delegating creator");
        } catch (Exception e) {
            // Expected: some form of Jackson exception
            assertTrue(e.getMessage() != null || e.getCause() != null);
        }
    }

}