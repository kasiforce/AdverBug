package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * Tests for the three-argument {@code deserialize(JsonParser, DeserializationContext, Object)}
 * method of UntypedObjectDeserializerNR, exercised through the public databind API
 * (ObjectReader value updates), plus basic untyped deserialization coverage.
 *
 * The merge tests verify the specified contract: values deserialized from JSON are
 * merged into the provided Map/Collection (intoValue) -- existing entries are updated,
 * new entries are added, JSON arrays are appended to existing Collections, and the
 * very same intoValue reference is returned.
 */
public class DeserializeTests {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    /*
     * Basic functionality: plain untyped deserialization into Maps, Lists and scalars.
     */

    @Test
    public void testReadUntypedObjectBuildsMapsListsAndScalars() throws Exception {
        Object result = MAPPER.readValue(
                "{\"name\":\"Bob\",\"age\":42,\"active\":true,"
                        + "\"tags\":[1,\"two\"],\"child\":{\"k\":false}}",
                Object.class);

        assertTrue(result instanceof Map);
        Map<?, ?> m = (Map<?, ?>) result;
        assertEquals(5, m.size());
        assertEquals("Bob", m.get("name"));
        assertEquals(Integer.valueOf(42), m.get("age"));
        assertEquals(Boolean.TRUE, m.get("active"));
        assertTrue(m.get("tags") instanceof List);
        assertEquals(Arrays.asList(Integer.valueOf(1), "two"), m.get("tags"));
        assertTrue(m.get("child") instanceof Map);
        assertEquals(Boolean.FALSE, ((Map<?, ?>) m.get("child")).get("k"));
    }

    @Test
    public void testReadUntypedArrayWithMixedAndNestedElements() throws Exception {
        Object result = MAPPER.readValue("[\"a\",3,false,null,[4],{\"x\":1}]", Object.class);

        assertTrue(result instanceof List);
        List<?> list = (List<?>) result;
        assertEquals(6, list.size());
        assertEquals("a", list.get(0));
        assertEquals(Integer.valueOf(3), list.get(1));
        assertEquals(Boolean.FALSE, list.get(2));
        assertNull(list.get(3));
        assertTrue(list.get(4) instanceof List);
        assertTrue(list.get(5) instanceof Map);
        assertEquals(Integer.valueOf(1), ((Map<?, ?>) list.get(5)).get("x"));
    }

    @Test
    public void testReadEmptyObjectAndArray() throws Exception {
        Object emptyObject = MAPPER.readValue("{}", Object.class);
        assertTrue(emptyObject instanceof Map);
        assertTrue(((Map<?, ?>) emptyObject).isEmpty());

        Object emptyArray = MAPPER.readValue("[]", Object.class);
        assertTrue(emptyArray instanceof List);
        assertTrue(((List<?>) emptyArray).isEmpty());
    }

    @Test
    public void testReadTopLevelScalarValues() throws Exception {
        assertEquals(Integer.valueOf(42), MAPPER.readValue("42", Object.class));
        assertEquals("text", MAPPER.readValue("\"text\"", Object.class));
        assertEquals(Boolean.TRUE, MAPPER.readValue("true", Object.class));
        assertNull(MAPPER.readValue("null", Object.class));
    }

    /*
     * Invalid input handling.
     */

    @Test(expected = JacksonException.class)
    public void testMalformedJsonFailsWithJacksonException() throws Exception {
        MAPPER.readValue("{\"a\":}", Object.class);
    }

    /*
     * Merging into an existing Map (intoValue): existing entries are updated, new
     * entries are added, and the same instance is returned.
     */

    @Test
    public void testMergeIntoMapUpdatesExistingAndAddsNewEntries() throws Exception {
        Map<String, Object> toUpdate = new LinkedHashMap<>();
        toUpdate.put("existing", 1);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(toUpdate)
                .readValue("{\"existing\":2,\"added\":\"new\"}");

        assertSame(toUpdate, result);
        assertEquals(2, toUpdate.size());
        assertEquals(Integer.valueOf(2), toUpdate.get("existing"));
        assertEquals("new", toUpdate.get("added"));
    }

    @Test
    public void testMergeIntoEmptyMapPopulatesAllEntries() throws Exception {
        Map<String, Object> toUpdate = new LinkedHashMap<>();

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(toUpdate)
                .readValue("{\"k1\":true,\"k2\":\"v2\"}");

        assertSame(toUpdate, result);
        assertEquals(2, toUpdate.size());
        assertEquals(Boolean.TRUE, toUpdate.get("k1"));
        assertEquals("v2", toUpdate.get("k2"));
    }

    @Test
    public void testMergeNestedMapRecursivelyIntoExistingNestedMap() throws Exception {
        Map<String, Object> nested = new LinkedHashMap<>();
        nested.put("x", 1);
        Map<String, Object> toUpdate = new LinkedHashMap<>();
        toUpdate.put("cfg", nested);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(toUpdate)
                .readValue("{\"cfg\":{\"x\":2,\"y\":3}}");

        assertSame(toUpdate, result);
        assertSame(nested, toUpdate.get("cfg"));
        assertEquals(2, nested.size());
        assertEquals(Integer.valueOf(2), nested.get("x"));
        assertEquals(Integer.valueOf(3), nested.get("y"));
    }

    @Test
    public void testMergeEmptyJsonObjectKeepsMapUnchanged() throws Exception {
        Map<String, Object> toUpdate = new LinkedHashMap<>();
        toUpdate.put("a", 1);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(toUpdate)
                .readValue("{}");

        assertSame(toUpdate, result);
        assertEquals(1, toUpdate.size());
        assertEquals(Integer.valueOf(1), toUpdate.get("a"));
    }

    /*
     * Merging into an existing Collection: JSON array elements are appended.
     */

    @Test
    public void testMergeJsonArrayAppendsToExistingCollection() throws Exception {
        List<Object> toUpdate = new ArrayList<>();
        toUpdate.add("first");

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(toUpdate)
                .readValue("[\"second\",42]");

        assertSame(toUpdate, result);
        assertEquals(Arrays.asList("first", "second", Integer.valueOf(42)), toUpdate);
    }

    @Test
    public void testMergeEmptyJsonArrayKeepsCollectionUnchanged() throws Exception {
        List<Object> toUpdate = new ArrayList<>();
        toUpdate.add(Integer.valueOf(1));

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(toUpdate)
                .readValue("[]");

        assertSame(toUpdate, result);
        assertEquals(1, toUpdate.size());
        assertEquals(Integer.valueOf(1), toUpdate.get(0));
    }

    /*
     * Values that are neither objects nor arrays fall through to plain
     * deserialization, replacing the old scalar value.
     */

    @Test
    public void testMergeScalarValueIsReplacedByDeserializedValue() throws Exception {
        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate("old")
                .readValue("\"fresh\"");

        assertEquals("fresh", result);
    }
}