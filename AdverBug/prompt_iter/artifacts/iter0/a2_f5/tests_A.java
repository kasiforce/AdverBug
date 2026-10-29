package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Unit tests for the merging ("update value") deserialization of
 * {@code UntypedObjectDeserializerNR}, exercised through the public
 * {@link ObjectMapper} API. Calling {@code readerFor(Object.class)
 * .withValueToUpdate(intoValue).readValue(...)} routes root-level
 * untyped deserialization into the three-argument
 * {@code deserialize(JsonParser, DeserializationContext, Object)} method.
 */
public class DeserializeTests {

    private final ObjectMapper MAPPER = new JsonMapper();

    // Basic (non-merging) untyped deserialization: behavior of the
    // delegated two-argument deserializer used for leaf and replaced values.

    @Test
    public void testPlainUntypedObject() throws Exception {
        Object value = MAPPER.readValue(
                "{\"name\":\"Bob\",\"age\":30,\"active\":true,\"score\":1.25,"
                        + "\"tags\":[\"a\",\"b\"],\"meta\":{\"id\":7,\"nil\":null}}",
                Object.class);
        assertTrue(value instanceof Map);
        Map<?, ?> map = (Map<?, ?>) value;
        assertEquals(6, map.size());
        assertEquals("Bob", map.get("name"));
        assertEquals(Integer.valueOf(30), map.get("age"));
        assertEquals(Boolean.TRUE, map.get("active"));
        assertEquals(Double.valueOf(1.25), map.get("score"));
        Object tags = map.get("tags");
        assertTrue(tags instanceof List);
        assertEquals(Arrays.asList("a", "b"), tags);
        Object meta = map.get("meta");
        assertTrue(meta instanceof Map);
        assertEquals(Integer.valueOf(7), ((Map<?, ?>) meta).get("id"));
        assertNull(((Map<?, ?>) meta).get("nil"));
    }

    @Test
    public void testPlainUntypedArray() throws Exception {
        Object value = MAPPER.readValue("[1,\"two\",true,null,{\"x\":2}]", Object.class);
        assertTrue(value instanceof List);
        List<?> list = (List<?>) value;
        assertEquals(5, list.size());
        assertEquals(Integer.valueOf(1), list.get(0));
        assertEquals("two", list.get(1));
        assertEquals(Boolean.TRUE, list.get(2));
        assertNull(list.get(3));
        assertTrue(list.get(4) instanceof Map);
        assertEquals(Integer.valueOf(2), ((Map<?, ?>) list.get(4)).get("x"));
    }

    // Merging into an existing Map.

    @Test
    public void testMergeIntoEmptyMap() throws Exception {
        Map<String, Object> into = new LinkedHashMap<>();
        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("{\"a\":1,\"b\":[true,null],\"c\":{\"d\":\"x\"}}");
        assertSame(into, result);
        assertEquals(3, into.size());
        assertEquals(Integer.valueOf(1), into.get("a"));
        Object b = into.get("b");
        assertTrue(b instanceof List);
        assertEquals(Arrays.asList(Boolean.TRUE, null), b);
        Object c = into.get("c");
        assertTrue(c instanceof Map);
        assertEquals("x", ((Map<?, ?>) c).get("d"));
    }

    @Test
    public void testMergeNestedMapInPlace() throws Exception {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("b", "old");
        inner.put("keep", "yes");
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("a", inner);
        into.put("c", "oldC");
        into.put("oldKey", "v");

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("{\"a\":{\"b\":10},\"c\":null,\"new\":[1,2]}");

        assertSame(into, result);
        // existing nested Map is merged in place, not replaced
        assertSame(inner, into.get("a"));
        assertEquals(Integer.valueOf(10), inner.get("b"));
        assertEquals("yes", inner.get("keep"));
        assertEquals(2, inner.size());
        // JSON null replaces the old scalar but keeps the key
        assertTrue(into.containsKey("c"));
        assertNull(into.get("c"));
        // entries not present in JSON are preserved
        assertEquals("v", into.get("oldKey"));
        // new key gets a freshly deserialized List value
        Object added = into.get("new");
        assertTrue(added instanceof List);
        assertEquals(Arrays.asList(Integer.valueOf(1), Integer.valueOf(2)), added);
        assertEquals(4, into.size());
    }

    @Test
    public void testMergeOverwritesScalarValues() throws Exception {
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("n", "old");
        into.put("s", Integer.valueOf(1));
        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("{\"n\":42,\"s\":\"one\"}");
        assertSame(into, result);
        assertEquals(Integer.valueOf(42), into.get("n"));
        assertEquals("one", into.get("s"));
    }

    @Test
    public void testMergeNestedEmptyObjectKeepsExistingValue() throws Exception {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("x", Integer.valueOf(1));
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("a", inner);

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("{\"a\":{}}");

        assertSame(into, result);
        assertSame(inner, into.get("a"));
        assertEquals(Integer.valueOf(1), inner.get("x"));
        assertEquals(1, inner.size());
        assertEquals(1, into.size());
    }

    // Merging into an existing Collection: append semantics.

    @Test
    public void testMergeAppendsToRootList() throws Exception {
        List<Object> into = new ArrayList<>();
        into.add(Integer.valueOf(1));
        into.add("keep");

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("[2,3]");

        assertSame(into, result);
        assertEquals(4, into.size());
        assertEquals(Integer.valueOf(1), into.get(0));
        assertEquals("keep", into.get(1));
        assertEquals(Integer.valueOf(2), into.get(2));
        assertEquals(Integer.valueOf(3), into.get(3));
    }

    @Test
    public void testMergeEmptyRootArrayKeepsExistingList() throws Exception {
        List<Object> into = new ArrayList<>();
        into.add("keep");

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("[]");

        assertSame(into, result);
        assertEquals(1, into.size());
        assertEquals("keep", into.get(0));
    }

    // Values whose existing type does not allow merging are replaced.

    @Test
    public void testMergeReplacesNonMapPropertyValue() throws Exception {
        Map<String, Object> original = new LinkedHashMap<>();
        original.put("a", Integer.valueOf(1));
        List<Object> oldList = new ArrayList<>();
        oldList.add(original);
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("list", oldList);

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("{\"list\":[{\"a\":2}]}");

        assertSame(into, result);
        Object updated = into.get("list");
        assertTrue(updated instanceof List);
        assertNotSame(oldList, updated);
        List<?> newList = (List<?>) updated;
        assertEquals(1, newList.size());
        Object elem = newList.get(0);
        assertTrue(elem instanceof Map);
        assertEquals(Integer.valueOf(2), ((Map<?, ?>) elem).get("a"));
        // previous List value is left untouched
        assertEquals(1, oldList.size());
        assertSame(original, oldList.get(0));
        assertEquals(Integer.valueOf(1), original.get("a"));
    }

    // Mismatched intoValue types delegate to plain deserialization.

    @Test
    public void testMergeArrayJsonWithNonCollectionIntoValue() throws Exception {
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("k", "v");

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("[1,2]");

        assertTrue(result instanceof List);
        assertNotSame(into, result);
        List<?> list = (List<?>) result;
        assertEquals(2, list.size());
        assertEquals(Integer.valueOf(1), list.get(0));
        assertEquals(Integer.valueOf(2), list.get(1));
        assertEquals(1, into.size());
        assertEquals("v", into.get("k"));
    }

    @Test
    public void testMergeObjectJsonWithNonMapIntoValue() throws Exception {
        List<Object> into = new ArrayList<>();
        into.add("keep");

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("{\"a\":1}");

        assertTrue(result instanceof Map);
        assertNotSame(into, result);
        assertEquals(Integer.valueOf(1), ((Map<?, ?>) result).get("a"));
        assertEquals(1, into.size());
        assertEquals("keep", into.get(0));
    }

    // Root-level null and malformed input.

    @Test
    public void testMergeNullRootValueReturnsNull() throws Exception {
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("k", "v");

        Object result = MAPPER.readerFor(Object.class).withValueToUpdate(into)
                .readValue("null");

        assertNull(result);
        assertEquals(1, into.size());
        assertEquals("v", into.get("k"));
    }

    @Test(expected = JacksonException.class)
    public void testMergeWithMalformedJsonThrows() throws Exception {
        Map<String, Object> into = new LinkedHashMap<>();
        into.put("a", Integer.valueOf(1));
        MAPPER.readerFor(Object.class).withValueToUpdate(into).readValue("{\"a\":");
    }
}