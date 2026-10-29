package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.*;

/**
 * Tests for the merging-aware ("intoValue") variant of
 * {@code UntypedObjectDeserializerNR#deserialize(JsonParser, DeserializationContext, Object)}:
 * merging into Maps (recursively), appending to Collections, delegation for
 * non-container and null targets, boundary conditions, and the non-merging instance.
 */
@SuppressWarnings("unchecked")
public class DeserializeTests
{
    private final JsonMapper mapper = JsonMapper.builder().build();

    private final UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();

    private DeserializationContext context() {
        return mapper.deserializationContext();
    }

    private Object mergeInto(String json, Object intoValue) throws Exception {
        try (JsonParser p = mapper.createParser(json)) {
            p.nextToken(); // position parser on the first token of the document
            return deser.deserialize(p, context(), intoValue);
        }
    }

    // // // Merging into Maps

    @Test
    public void testMergeScalarsIntoExistingMap() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);
        existing.put("b", "x");

        Map<String,Object> result = (Map<String,Object>) mergeInto("{\"a\":10,\"b\":\"y\"}", existing);

        assertSame(existing, result);
        assertEquals(Integer.valueOf(10), result.get("a"));
        assertEquals("y", result.get("b"));
        assertEquals(2, result.size());
    }

    @Test
    public void testMergeAddsNewKeysButSkipsExplicitNulls() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Map<String,Object> result = (Map<String,Object>) mergeInto("{\"a\":1,\"c\":true,\"d\":null}", existing);

        assertSame(existing, result);
        assertEquals(2, result.size());
        assertEquals(Integer.valueOf(1), result.get("a"));
        assertEquals(Boolean.TRUE, result.get("c"));
        assertFalse(result.containsKey("d"));
    }

    @Test
    public void testMergeNestedMapsRecursively() throws Exception {
        Map<String,Object> inner = new LinkedHashMap<>();
        inner.put("x", 1);
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("n", inner);

        Map<String,Object> result = (Map<String,Object>) mergeInto("{\"n\":{\"x\":5,\"y\":6}}", existing);

        assertSame(existing, result);
        assertSame(inner, result.get("n"));
        assertEquals(Integer.valueOf(5), inner.get("x"));
        assertEquals(Integer.valueOf(6), inner.get("y"));
    }

    @Test
    public void testScalarValueReplacesNonContainerMergeTarget() throws Exception {
        Map<String,Object> inner = new LinkedHashMap<>();
        inner.put("x", 1);
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("n", inner);

        Map<String,Object> result = (Map<String,Object>) mergeInto("{\"n\":42}", existing);

        assertSame(existing, result);
        assertEquals(Integer.valueOf(42), result.get("n"));
    }

    @Test
    public void testMergeCollectionValueInsideMap() throws Exception {
        List<Object> list = new ArrayList<>(Arrays.asList("x"));
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("l", list);

        Map<String,Object> result = (Map<String,Object>) mergeInto("{\"l\":[\"y\"]}", existing);

        assertSame(list, result.get("l"));
        assertEquals(Arrays.asList("x", "y"), list);
    }

    @Test
    public void testNullValueReplacesExistingValue() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Map<String,Object> result = (Map<String,Object>) mergeInto("{\"a\":null}", existing);

        assertSame(existing, result);
        assertTrue(result.containsKey("a"));
        assertNull(result.get("a"));
    }

    // // // Merging into Collections

    @Test
    public void testMergeAppendsToExistingCollection() throws Exception {
        List<Object> existing = new ArrayList<>(Arrays.asList(1, 2));

        Object result = mergeInto("[3, 4]", existing);

        assertSame(existing, result);
        assertEquals(Arrays.asList(1, 2, 3, 4), existing);
    }

    // // // Boundary conditions

    @Test
    public void testEmptyObjectKeepsMapUnchanged() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Object result = mergeInto("{}", existing);

        assertSame(existing, result);
        assertEquals(1, existing.size());
    }

    @Test
    public void testEmptyArrayKeepsCollectionUnchanged() throws Exception {
        List<Object> existing = new ArrayList<>(Arrays.asList("a"));

        Object result = mergeInto("[]", existing);

        assertSame(existing, result);
        assertEquals(Arrays.asList("a"), existing);
    }

    @Test
    public void testEndObjectTokenReturnsIntoValueUnchanged() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        try (JsonParser p = mapper.createParser("{}")) {
            p.nextToken(); // START_OBJECT
            p.nextToken(); // END_OBJECT
            assertSame(existing, deser.deserialize(p, context(), existing));
        }
    }

    @Test
    public void testEndArrayTokenReturnsIntoValueUnchanged() throws Exception {
        List<Object> existing = new ArrayList<>(Arrays.asList("a"));

        try (JsonParser p = mapper.createParser("[]")) {
            p.nextToken(); // START_ARRAY
            p.nextToken(); // END_ARRAY
            assertSame(existing, deser.deserialize(p, context(), existing));
        }
    }

    @Test
    public void testMergeWhenParserPositionedAtFieldName() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        try (JsonParser p = mapper.createParser("{\"a\":7}")) {
            p.nextToken(); // START_OBJECT
            p.nextToken(); // FIELD_NAME
            Object result = deser.deserialize(p, context(), existing);
            assertSame(existing, result);
            assertEquals(Integer.valueOf(7), existing.get("a"));
        }
    }

    @Test
    public void testParserAdvancedToEndObjectAfterMerge() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        try (JsonParser p = mapper.createParser("{\"a\":2,\"b\":3}")) {
            p.nextToken(); // START_OBJECT
            deser.deserialize(p, context(), existing);
            assertEquals(JsonToken.END_OBJECT, p.currentToken());
        }
        assertEquals(Integer.valueOf(2), existing.get("a"));
        assertEquals(Integer.valueOf(3), existing.get("b"));
    }

    // // // Delegation for non-container targets

    @Test
    public void testNonContainerIntoValueDelegatesToFullDeserialization() throws Exception {
        Object result = mergeInto("{\"k\":\"v\"}", "not-a-container");
        assertTrue(result instanceof Map<?, ?>);
        assertEquals("v", ((Map<?, ?>) result).get("k"));

        // A Collection with object content is replaced by a newly built Map
        result = mergeInto("{\"k\":\"v\"}", new ArrayList<Object>());
        assertTrue(result instanceof Map<?, ?>);
        assertEquals("v", ((Map<?, ?>) result).get("k"));

        // A Map with array content is replaced by a newly built List
        result = mergeInto("[1, 2]", new LinkedHashMap<String, Object>());
        assertTrue(result instanceof List<?>);
        assertEquals(Arrays.asList(1, 2), result);
    }

    @Test
    public void testNullIntoValueDelegatesToFullDeserialization() throws Exception {
        Object result = mergeInto("{\"k\":\"v\"}", null);
        assertTrue(result instanceof Map<?, ?>);
        assertEquals("v", ((Map<?, ?>) result).get("k"));

        result = mergeInto("[true, 1]", null);
        assertTrue(result instanceof List<?>);
        assertEquals(Arrays.asList(Boolean.TRUE, Integer.valueOf(1)), result);
    }

    @Test
    public void testScalarInputDelegatesToFullDeserialization() throws Exception {
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        assertEquals(Integer.valueOf(42), mergeInto("42", existing));
        assertEquals("hello", mergeInto("\"hello\"", existing));
        assertEquals(Integer.valueOf(1), existing.get("a"));
    }

    // // // Non-merging instance

    @Test
    public void testNonMergingInstanceReplacesInsteadOfMerges() throws Exception {
        UntypedObjectDeserializerNR nonMerging = new UntypedObjectDeserializerNR(true);
        Map<String,Object> existing = new LinkedHashMap<>();
        existing.put("a", 1);

        Object result;
        try (JsonParser p = mapper.createParser("{\"a\":10}")) {
            p.nextToken(); // START_OBJECT
            result = nonMerging.deserialize(p, context(), existing);
        }

        assertTrue(result instanceof Map<?, ?>);
        assertNotSame(existing, result);
        assertEquals(Integer.valueOf(1), existing.get("a"));
        assertEquals(Integer.valueOf(10), ((Map<?, ?>) result).get("a"));
    }
}