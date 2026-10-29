package tools.jackson.databind.deser.jdk;

import java.util.EnumMap;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests for EnumMapDeserializer._deserializeUsingProperties(), exercised through the
 * public ObjectMapper API. The method is reached when deserializing an EnumMap
 * sub-class that declares a property-based {@code @JsonCreator} constructor: the JSON
 * object may then contain both creator properties ("label"/"count" below) and regular
 * EnumMap entries, and the deserializer must combine creator-based instantiation with
 * buffered map properties.
 */
public class _deserializeUsingPropertiesTests
{
    public enum TestColor { RED, GREEN, BLUE, PURPLE }

    // EnumMap sub-class with a single property-based creator argument
    public static class CreatorEnumMap extends EnumMap<TestColor, String>
    {
        private static final long serialVersionUID = 1L;

        private final String label;

        @JsonCreator
        public CreatorEnumMap(@JsonProperty("label") String label) {
            super(TestColor.class);
            this.label = label;
        }

        public String getLabel() { return label; }
    }

    // EnumMap sub-class with two property-based creator arguments
    public static class TwoCreatorEnumMap extends EnumMap<TestColor, String>
    {
        private static final long serialVersionUID = 1L;

        private final String label;
        private final String count;

        @JsonCreator
        public TwoCreatorEnumMap(@JsonProperty("label") String label,
                @JsonProperty("count") String count) {
            super(TestColor.class);
            this.label = label;
            this.count = count;
        }

        public String getLabel() { return label; }
        public String getCount() { return count; }
    }

    private final ObjectMapper MAPPER = new JsonMapper();

    // Basic case: creator property comes first, remaining entries are
    // deserialized into the already-built EnumMap.
    @Test
    public void testBasicDeserializationWithCreatorPropertyFirst() {
        CreatorEnumMap result = MAPPER.readValue(
                "{\"label\":\"x\",\"RED\":\"r\",\"GREEN\":\"g\"}", CreatorEnumMap.class);
        assertEquals("x", result.getLabel());
        assertEquals(2, result.size());
        assertEquals("r", result.get(TestColor.RED));
        assertEquals("g", result.get(TestColor.GREEN));
    }

    // A map entry that precedes the creator property must be buffered via
    // bufferMapProperty() and still end up in the final map.
    @Test
    public void testCreatorPropertyAfterMapEntries() {
        CreatorEnumMap result = MAPPER.readValue(
                "{\"RED\":\"r\",\"label\":\"x\"}", CreatorEnumMap.class);
        assertEquals("x", result.getLabel());
        assertEquals(1, result.size());
        assertEquals("r", result.get(TestColor.RED));
    }

    // Two creator properties interleaved with regular entries: entries seen
    // before creator completion are buffered, entries after the last creator
    // property are read into the built map.
    @Test
    public void testMultipleCreatorPropertiesInterleavedWithEntries() {
        TwoCreatorEnumMap result = MAPPER.readValue(
                "{\"RED\":\"r\",\"label\":\"x\",\"GREEN\":\"g\",\"count\":\"7\",\"BLUE\":\"b\"}",
                TwoCreatorEnumMap.class);
        assertEquals("x", result.getLabel());
        assertEquals("7", result.getCount());
        assertEquals(3, result.size());
        assertEquals("r", result.get(TestColor.RED));
        assertEquals("g", result.get(TestColor.GREEN));
        assertEquals("b", result.get(TestColor.BLUE));
    }

    // No creator property at all: entries are buffered and the map is built
    // at the end of the JSON object, with missing creator arguments null.
    @Test
    public void testOnlyMapEntriesWithoutCreatorProperties() {
        CreatorEnumMap result = MAPPER.readValue(
                "{\"RED\":\"r\",\"BLUE\":\"b\"}", CreatorEnumMap.class);
        assertNull(result.getLabel());
        assertEquals(2, result.size());
        assertEquals("r", result.get(TestColor.RED));
        assertEquals("b", result.get(TestColor.BLUE));
    }

    // Empty JSON object: no entries, no creator parameters assigned.
    @Test
    public void testEmptyJsonObject() {
        CreatorEnumMap result = MAPPER.readValue("{}", CreatorEnumMap.class);
        assertTrue(result.isEmpty());
        assertNull(result.getLabel());
    }

    // JSON null as the creator property value still counts as an assigned
    // creator parameter.
    @Test
    public void testNullCreatorPropertyValue() {
        CreatorEnumMap result = MAPPER.readValue(
                "{\"label\":null,\"RED\":\"r\"}", CreatorEnumMap.class);
        assertNull(result.getLabel());
        assertEquals(1, result.size());
        assertEquals("r", result.get(TestColor.RED));
    }

    // JSON null as a map value must not fail deserialization of the entry;
    // remaining valid entries are still added.
    @Test
    public void testNullMapValuesDoNotFail() {
        CreatorEnumMap result = MAPPER.readValue(
                "{\"label\":\"x\",\"RED\":null,\"GREEN\":\"g\"}", CreatorEnumMap.class);
        assertEquals("x", result.getLabel());
        assertNull(result.get(TestColor.RED));
        assertEquals("g", result.get(TestColor.GREEN));
    }

    // Unknown enum key, READ_UNKNOWN_ENUM_VALUES_AS_NULL not enabled:
    // deserialization should throw a Jackson exception.
    @Test
    public void testUnknownEnumKeyThrowsException() {
        try {
            MAPPER.readValue("{\"label\":\"x\",\"PURPLE\":\"p\"}", CreatorEnumMap.class);
            fail("Deserializing an unknown Enum key should throw an exception");
        } catch (JacksonException e) {
            // expected
        }
    }

    // Unknown enum key with READ_UNKNOWN_ENUM_VALUES_AS_NULL enabled: key
    // deserializer returns null, the entry is skipped, and the rest of the
    // object is still deserialized.
    @Test
    public void testReadUnknownEnumValuesAsNullSkipsEntry() {
        ObjectMapper mapper = JsonMapper.builder()
                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        CreatorEnumMap result = mapper.readValue(
                "{\"label\":\"x\",\"PURPLE\":\"p\",\"RED\":\"r\"}", CreatorEnumMap.class);
        assertEquals("x", result.getLabel());
        assertEquals(1, result.size());
        assertEquals("r", result.get(TestColor.RED));
        assertNull(result.get(TestColor.PURPLE));
    }

    // A value that cannot be deserialized as the declared value type should
    // throw a Jackson exception (wrapped via wrapAndThrow).
    @Test
    public void testInvalidValueTypeThrowsException() {
        try {
            MAPPER.readValue("{\"label\":\"x\",\"RED\":{\"a\":1}}", CreatorEnumMap.class);
            fail("Should not accept an Object value for a String-valued map entry");
        } catch (JacksonException e) {
            // expected
        }
    }

    // Input that does not start with a JSON object should be rejected.
    @Test
    public void testNonObjectInputThrowsException() {
        try {
            MAPPER.readValue("[\"RED\"]", CreatorEnumMap.class);
            fail("Should not accept array input for an EnumMap");
        } catch (JacksonException e) {
            // expected
        }
    }
}