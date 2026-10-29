package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Unit tests for {@link EnumMapDeserializer} covering EnumMap deserialization
 * behavior (per-key key-deserializer invocation, value deserialization, null
 * handling and unknown-key handling) through public {@link JsonMapper}
 * entry points that drive the deserializer (including its
 * property-based-creator handling path).
 */
public class _deserializeUsingPropertiesTests {

    public enum TestEnum {
        A, B, C
    }

    public static class EnumMapWrapper {
        public EnumMap<TestEnum, Integer> map;
    }

    private static final TypeReference<EnumMap<TestEnum, Integer>> ENUM_MAP_TYPE =
            new TypeReference<EnumMap<TestEnum, Integer>>() { };

    private final JsonMapper defaultMapper = JsonMapper.builder().build();

    @Test
    public void testBasicDeserialization() throws Exception {
        EnumMap<TestEnum, Integer> result = defaultMapper.readValue(
                "{\"A\": 1, \"B\": 2, \"C\": 3}", ENUM_MAP_TYPE);
        assertNotNull(result);
        assertTrue(result instanceof EnumMap);
        assertEquals(3, result.size());
        assertEquals(Integer.valueOf(1), result.get(TestEnum.A));
        assertEquals(Integer.valueOf(2), result.get(TestEnum.B));
        assertEquals(Integer.valueOf(3), result.get(TestEnum.C));
    }

    @Test
    public void testEmptyObjectDeserialization() throws Exception {
        EnumMap<TestEnum, Integer> result = defaultMapper.readValue("{}", ENUM_MAP_TYPE);
        assertNotNull(result);
        assertTrue(result.isEmpty());
        assertEquals(0, result.size());
    }

    @Test
    public void testEnumKeyOrderingPreserved() throws Exception {
        // Entries appear in non-natural order; EnumMap must still expose
        // keys in enum-declaration order.
        EnumMap<TestEnum, Integer> result = defaultMapper.readValue(
                "{\"C\": 3, \"A\": 1}", ENUM_MAP_TYPE);
        assertEquals(2, result.size());
        assertEquals(Arrays.asList(TestEnum.A, TestEnum.C),
                new ArrayList<TestEnum>(result.keySet()));
        assertEquals(Integer.valueOf(1), result.get(TestEnum.A));
        assertEquals(Integer.valueOf(3), result.get(TestEnum.C));
    }

    @Test
    public void testDuplicateKeysLastValueWins() throws Exception {
        EnumMap<TestEnum, Integer> result = defaultMapper.readValue(
                "{\"A\": 1, \"A\": 2}", ENUM_MAP_TYPE);
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(2), result.get(TestEnum.A));
    }

    @Test
    public void testNullValuesRetainedByDefault() throws Exception {
        EnumMap<TestEnum, Integer> result = defaultMapper.readValue(
                "{\"A\": null, \"B\": 2}", ENUM_MAP_TYPE);
        assertEquals(2, result.size());
        assertTrue(result.containsKey(TestEnum.A));
        assertNull(result.get(TestEnum.A));
        assertEquals(Integer.valueOf(2), result.get(TestEnum.B));
    }

    @Test
    public void testUnknownEnumKeyThrowsException() throws Exception {
        try {
            defaultMapper.readValue("{\"UNKNOWN_KEY\": 1}", ENUM_MAP_TYPE);
            fail("Expected an exception for a key that is not a declared Enum instance name");
        } catch (JacksonException e) {
            // expected: value not one of declared Enum instance names
        }
    }

    @Test
    public void testUnknownEnumKeyAsNullSkipsEntry() throws Exception {
        JsonMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        EnumMap<TestEnum, Integer> result = mapper.readValue(
                "{\"UNKNOWN_KEY\": 1, \"A\": 5}", ENUM_MAP_TYPE);
        assertNotNull(result);
        // Null cannot be an EnumMap key, so the whole entry is skipped.
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(5), result.get(TestEnum.A));
        assertFalse(result.containsKey(TestEnum.B));
        assertFalse(result.containsKey(TestEnum.C));
    }

    @Test
    public void testInvalidValueThrowsException() throws Exception {
        try {
            defaultMapper.readValue("{\"A\": \"not-a-number\"}", ENUM_MAP_TYPE);
            fail("Expected an exception for a value that cannot be deserialized");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testNonObjectInputThrowsException() throws Exception {
        try {
            defaultMapper.readValue("[1, 2]", ENUM_MAP_TYPE);
            fail("Expected an exception when reading an array as an EnumMap");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testEnumMapAsBeanProperty() throws Exception {
        EnumMapWrapper result = defaultMapper.readValue(
                "{\"map\": {\"A\": 1, \"B\": 2}}", EnumMapWrapper.class);
        assertNotNull(result);
        assertNotNull(result.map);
        assertTrue(result.map instanceof EnumMap);
        assertEquals(2, result.map.size());
        assertEquals(Integer.valueOf(1), result.map.get(TestEnum.A));
        assertEquals(Integer.valueOf(2), result.map.get(TestEnum.B));
    }
}