package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

public class DeserializeTests
{
    private final JsonMapper MAPPER = new JsonMapper();

    // Basic merging: existing entries updated in place, new entries added,
    // untouched entries preserved.
    @Test
    public void testMergeScalarValuesIntoMap() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);
        existing.put("b", "text");
        existing.put("d", Boolean.FALSE);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"a\": 2, \"b\": \"changed\", \"c\": true, \"d\": false }");

        assertSame(existing, result);
        assertEquals(4, existing.size());
        assertEquals(Integer.valueOf(2), existing.get("a"));
        assertEquals("changed", existing.get("b"));
        assertEquals(Boolean.TRUE, existing.get("c"));
        assertEquals(Boolean.FALSE, existing.get("d"));
    }

    // Nested maps must be merged recursively, keeping the same instance
    // and preserving entries absent from the incoming JSON.
    @Test
    public void testDeepMergeOfNestedMaps() throws Exception
    {
        Map<String,Object> nested = new LinkedHashMap<>();
        nested.put("x", 1);
        nested.put("keep", "me");
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("cfg", nested);
        existing.put("n", 5);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"cfg\": {\"y\": 2, \"x\": 10}}");

        assertSame(existing, result);
        assertEquals(Integer.valueOf(5), existing.get("n"));
        assertSame(nested, existing.get("cfg"));
        assertEquals(3, nested.size());
        assertEquals(Integer.valueOf(10), nested.get("x"));
        assertEquals("me", nested.get("keep"));
        assertEquals(Integer.valueOf(2), nested.get("y"));
    }

    // Empty JSON object: parser reaches END_OBJECT right away,
    // intoValue must be returned as-is, unchanged.
    @Test
    public void testEmptyObjectLeavesMapUnchanged() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{}");

        assertSame(existing, result);
        assertEquals(1, existing.size());
        assertEquals(Integer.valueOf(1), existing.get("a"));
    }

    // Empty JSON array: parser reaches END_ARRAY right away,
    // intoValue Collection must be returned as-is, unchanged.
    @Test
    public void testEmptyArrayLeavesCollectionUnchanged() throws Exception
    {
        List<Object> existing = new ArrayList<>();
        existing.add(1);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("[]");

        assertSame(existing, result);
        assertEquals(1, existing.size());
        assertEquals(Integer.valueOf(1), existing.get(0));
    }

    // Merging into a Collection means appending the incoming elements.
    @Test
    public void testArrayValuesAppendedToExistingCollection() throws Exception
    {
        List<Object> existing = new ArrayList<>();
        existing.add("first");

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("[123, \"second\"]");

        assertSame(existing, result);
        assertEquals(3, existing.size());
        assertEquals("first", existing.get(0));
        assertEquals(Integer.valueOf(123), existing.get(1));
        assertEquals("second", existing.get(2));
    }

    // Array JSON cannot be merged into a Map intoValue: a fresh List is
    // delegated to and returned; the original Map must stay untouched.
    @Test
    public void testArrayJsonWithMapIntoValueIsReplacedByList() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("[1, 2]");

        assertTrue(result instanceof List);
        assertNotSame(existing, result);
        List<?> list = (List<?>) result;
        assertEquals(2, list.size());
        assertEquals(Integer.valueOf(1), list.get(0));
        assertEquals(Integer.valueOf(2), list.get(1));
        assertEquals(1, existing.size());
        assertEquals(Integer.valueOf(1), existing.get("a"));
    }

    // JSON null as the value of an existing key must overwrite it.
    @Test
    public void testNullValueOverwritesExistingMapEntry() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 5);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"a\": null}");

        assertSame(existing, result);
        assertTrue(existing.containsKey("a"));
        assertNull(existing.get("a"));
    }

    // Scalar root value with a Map intoValue: no merge is possible,
    // the deserialized scalar is returned and the Map is untouched.
    @Test
    public void testScalarJsonWithMapIntoValueDelegatesWithoutMerging() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("42");

        assertEquals(Integer.valueOf(42), result);
        assertNotSame(existing, result);
        assertEquals(1, existing.size());
        assertEquals(Integer.valueOf(1), existing.get("a"));
    }

    // Object JSON with a non-Map, non-Collection intoValue: falls through
    // to regular deserialization, returning a new Map.
    @Test
    public void testObjectJsonWithNonMapIntoValueIsReplacedByNewMap() throws Exception
    {
        Object existing = "old";

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"a\": 1}");

        assertTrue(result instanceof Map);
        assertNotSame(existing, result);
        assertEquals(Integer.valueOf(1), ((Map<?,?>) result).get("a"));
        assertEquals("old", existing);
    }

    // Within a merged object, an existing scalar value replaced by a
    // JSON object must be substituted by a freshly deserialized Map.
    @Test
    public void testExistingScalarReplacedByObjectValue() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("cfg", "old");

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"cfg\": {\"a\": 1}}");

        assertSame(existing, result);
        assertTrue(existing.get("cfg") instanceof Map);
        Map<?,?> cfg = (Map<?,?>) existing.get("cfg");
        assertEquals(1, cfg.size());
        assertEquals(Integer.valueOf(1), cfg.get("a"));
    }

    // Within a merged object, an existing Map value replaced by a JSON
    // array must be substituted by a freshly deserialized List.
    @Test
    public void testNestedArrayValueReplacesExistingMapValue() throws Exception
    {
        Map<String,Object> nested = new LinkedHashMap<>();
        nested.put("x", 1);
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("cfg", nested);

        Object result = MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"cfg\": [1, 2]}");

        assertSame(existing, result);
        assertTrue(existing.get("cfg") instanceof List);
        List<?> list = (List<?>) existing.get("cfg");
        assertEquals(2, list.size());
        assertEquals(Integer.valueOf(1), list.get(0));
        assertEquals(Integer.valueOf(2), list.get(1));
        // The old nested Map must not have been modified
        assertEquals(1, nested.size());
        assertEquals(Integer.valueOf(1), nested.get("x"));
    }

    // Malformed JSON encountered while merging must raise a JacksonException.
    @Test(expected = JacksonException.class)
    public void testMalformedJsonDuringMergeThrowsException() throws Exception
    {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        MAPPER.readerFor(Object.class)
                .withValueToUpdate(existing)
                .readValue("{\"a\": ,}");
    }
}