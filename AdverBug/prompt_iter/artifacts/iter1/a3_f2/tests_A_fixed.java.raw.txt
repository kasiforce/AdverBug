import java.util.EnumMap;
import java.util.Iterator;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

public class DeserializeTests {

    public enum TestEnum { A, B, C }

    private final ObjectMapper MAPPER = new JsonMapper();

    @Test
    public void testBasicEnumMapDeserialization() throws Exception {
        String json = "{\"A\": 1, \"B\": 2}";
        EnumMap<TestEnum, Integer> result = MAPPER.readValue(json,
                new TypeReference<EnumMap<TestEnum, Integer>>() { });
        assertEquals(2, result.size());
        assertEquals(Integer.valueOf(1), result.get(TestEnum.A));
        assertEquals(Integer.valueOf(2), result.get(TestEnum.B));
        assertFalse(result.containsKey(TestEnum.C));
    }

    @Test
    public void testEmptyObjectGivesEmptyMap() throws Exception {
        EnumMap<TestEnum, Integer> result = MAPPER.readValue("{}",
                new TypeReference<EnumMap<TestEnum, Integer>>() { });
        assertNotNull(result);
        assertTrue(result.isEmpty());
        assertEquals(0, result.size());
    }

    @Test
    public void testExplicitNullValuesRetainedByDefault() throws Exception {
        String json = "{\"A\": null, \"B\": 5}";
        EnumMap<TestEnum, Integer> result = MAPPER.readValue(json,
                new TypeReference<EnumMap<TestEnum, Integer>>() { });
        assertEquals(2, result.size());
        assertTrue(result.containsKey(TestEnum.A));
        assertNull(result.get(TestEnum.A));
        assertEquals(Integer.valueOf(5), result.get(TestEnum.B));
    }

    @Test
    public void testUnknownEnumKeyFailsByDefault() throws Exception {
        String json = "{\"A\": 1, \"X\": 2}";
        try {
            MAPPER.readValue(json, new TypeReference<EnumMap<TestEnum, Integer>>() { });
            fail("Expected an exception for unknown enum key 'X'");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testUnknownEnumKeySkippedWhenConfigured() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        String json = "{\"X\": 1, \"A\": 2}";
        EnumMap<TestEnum, Integer> result = mapper.readValue(json,
                new TypeReference<EnumMap<TestEnum, Integer>>() { });
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(2), result.get(TestEnum.A));
        assertFalse(result.containsValue(Integer.valueOf(1)));
    }

    @Test
    public void testEntryIterationOrderFollowsEnumOrdinals() throws Exception {
        String json = "{\"C\": 3, \"A\": 1, \"B\": 2}";
        EnumMap<TestEnum, Integer> result = MAPPER.readValue(json,
                new TypeReference<EnumMap<TestEnum, Integer>>() { });
        Iterator<Map.Entry<TestEnum, Integer>> it = result.entrySet().iterator();
        assertTrue(it.hasNext());
        assertEquals(TestEnum.A, it.next().getKey());
        assertEquals(TestEnum.B, it.next().getKey());
        assertEquals(TestEnum.C, it.next().getKey());
        assertFalse(it.hasNext());
    }

    @Test
    public void testDuplicateKeysLastValueWins() throws Exception {
        String json = "{\"A\": 1, \"A\": 2}";
        EnumMap<TestEnum, Integer> result = MAPPER.readValue(json,
                new TypeReference<EnumMap<TestEnum, Integer>>() { });
        assertEquals(1, result.size());
        assertEquals(Integer.valueOf(2), result.get(TestEnum.A));
    }

    @Test
    public void testStringValueValues() throws Exception {
        String json = "{\"B\": \"bravo\", \"A\": \"alpha\"}";
        EnumMap<TestEnum, String> result = MAPPER.readValue(json,
                new TypeReference<EnumMap<TestEnum, String>>() { });
        assertEquals(2, result.size());
        assertEquals("alpha", result.get(TestEnum.A));
        assertEquals("bravo", result.get(TestEnum.B));
    }

    @Test
    public void testNestedObjectValueFails() throws Exception {
        String json = "{\"A\": {\"x\": 1}}";
        try {
            MAPPER.readValue(json, new TypeReference<EnumMap<TestEnum, Integer>>() { });
            fail("Expected an exception when a value cannot be deserialized into Integer");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testScalarInputFails() throws Exception {
        try {
            MAPPER.readValue("42", new TypeReference<EnumMap<TestEnum, Integer>>() { });
            fail("Expected an exception for non-object input");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testDeserializeIntoPrePopulatedInstance() throws Exception {
        EnumMap<TestEnum, Integer> template = new EnumMap<TestEnum, Integer>(TestEnum.class);
        template.put(TestEnum.C, 99);
        EnumMap<TestEnum, Integer> result = MAPPER
                .readerFor(new TypeReference<EnumMap<TestEnum, Integer>>() { })
                .withValueToUpdate(template)
                .readValue("{\"A\": 1}");
        assertSame(template, result);
        assertEquals(2, result.size());
        assertEquals(Integer.valueOf(1), result.get(TestEnum.A));
        assertEquals(Integer.valueOf(99), result.get(TestEnum.C));
    }
}