package tools.jackson.databind.deser.jdk;

import java.util.EnumMap;
import java.util.Iterator;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class DeserializeTests {

    public enum TestKey {
        A, B, C
    }

    private final ObjectMapper mapper = new JsonMapper();

    @Test
    public void testBasicDeserialization() throws Exception {
        String json = "{\"A\": 1, \"B\": 2}";
        EnumMap<TestKey, Integer> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        assertNotNull(result);
        assertTrue(result instanceof EnumMap);
        assertEquals(2, result.size());
        assertEquals(Integer.valueOf(1), result.get(TestKey.A));
        assertEquals(Integer.valueOf(2), result.get(TestKey.B));
        assertFalse(result.containsKey(TestKey.C));
    }

    @Test
    public void testEmptyObjectGivesEmptyMap() throws Exception {
        EnumMap<TestKey, Integer> result = mapper.readValue("{}",
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        assertNotNull(result);
        assertTrue(result.isEmpty());
        assertEquals(0, result.size());
    }

    @Test
    public void testNullValuesAreRetained() throws Exception {
        String json = "{\"A\": null, \"B\": 2}";
        EnumMap<TestKey, Integer> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        assertEquals(2, result.size());
        assertTrue(result.containsKey(TestKey.A));
        assertNull(result.get(TestKey.A));
        assertEquals(Integer.valueOf(2), result.get(TestKey.B));
    }

    @Test
    public void testMixedValueTypes() throws Exception {
        String json = "{\"A\": \"text\", \"B\": true, \"C\": 3.5}";
        EnumMap<TestKey, Object> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Object>>() { });
        assertEquals(3, result.size());
        assertEquals("text", result.get(TestKey.A));
        assertEquals(Boolean.TRUE, result.get(TestKey.B));
        assertEquals(Double.valueOf(3.5), result.get(TestKey.C));
    }

    @Test
    public void testUnknownEnumKeyThrows() throws Exception {
        String json = "{\"X\": 1}";
        try {
            mapper.readValue(json, new TypeReference<EnumMap<TestKey, Integer>>() { });
            fail("Expected a JacksonException for unknown enum key 'X'");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testUnknownEnumKeySkippedWithFeature() throws Exception {
        ObjectMapper featureMapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        String json = "{\"X\": 1, \"A\": 2}";
        EnumMap<TestKey, Integer> result = featureMapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(2), result.get(TestKey.A));
        assertFalse(result.containsKey(TestKey.B));
    }

    @Test
    public void testNonObjectInputThrows() throws Exception {
        try {
            mapper.readValue("[1, 2]", new TypeReference<EnumMap<TestKey, Integer>>() { });
            fail("Expected a JacksonException when input is not a JSON object");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testDuplicateKeysLastValueWins() throws Exception {
        String json = "{\"A\": 1, \"A\": 2}";
        EnumMap<TestKey, Integer> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(2), result.get(TestKey.A));
    }

    @Test
    public void testStringValues() throws Exception {
        String json = "{\"A\": \"alpha\", \"C\": \"gamma\"}";
        EnumMap<TestKey, String> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, String>>() { });
        assertEquals(2, result.size());
        assertEquals("alpha", result.get(TestKey.A));
        assertEquals("gamma", result.get(TestKey.C));
    }

    @Test
    public void testEnumKeyOrderPreserved() throws Exception {
        String json = "{\"C\": 3, \"A\": 1}";
        EnumMap<TestKey, Integer> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        Iterator<TestKey> it = result.keySet().iterator();
        assertTrue(it.hasNext());
        assertEquals(TestKey.A, it.next());
        assertEquals(TestKey.C, it.next());
        assertFalse(it.hasNext());
    }

    @Test
    public void testRepeatedDeserializationIsDeterministic() throws Exception {
        String json = "{\"A\": 1, \"B\": 2, \"C\": 3}";
        EnumMap<TestKey, Integer> first = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        EnumMap<TestKey, Integer> second = mapper.readValue(json,
                new TypeReference<EnumMap<TestKey, Integer>>() { });
        assertEquals(first, second);
        assertEquals(first.hashCode(), second.hashCode());
    }
}