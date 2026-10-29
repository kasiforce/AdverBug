package tools.jackson.databind.deser.jdk;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.core.JsonParser;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Tests for merging deserialization performed by
 * UntypedObjectDeserializerNR.deserialize(JsonParser, DeserializationContext, Object).
 * The deserializer under test is invoked directly, with the parser positioned at
 * the token the method expects and with an existing value ("intoValue") to merge into.
 */
public class DeserializeTests {
    private final JsonMapper mapper = new JsonMapper();

    @Test
    public void testMergeIntoMapUpdatesExistingAndAddsNewEntries() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);
        map.put("b", "x");

        try (JsonParser p = mapper.createParser("{\"a\":2,\"c\":true}")) {
            p.nextToken(); // START_OBJECT
            Object result = deser.deserialize(p, null, map);

            assertSame(map, result);
            assertEquals(3, map.size());
            assertEquals(Integer.valueOf(2), map.get("a"));
            assertEquals("x", map.get("b"));
            assertEquals(Boolean.TRUE, map.get("c"));
        }
    }

    @Test
    public void testMergeIntoMapMergesNestedMapsInPlace() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> nested = new LinkedHashMap<>();
        nested.put("x", 1);
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", nested);

        try (JsonParser p = mapper.createParser("{\"a\":{\"y\":2,\"z\":\"s\"}}")) {
            p.nextToken(); // START_OBJECT
            Object result = deser.deserialize(p, null, map);

            assertSame(map, result);
            assertSame(nested, map.get("a")); // merged in place, not replaced
            assertEquals(3, nested.size());
            assertEquals(Integer.valueOf(1), nested.get("x"));
            assertEquals(Integer.valueOf(2), nested.get("y"));
            assertEquals("s", nested.get("z"));
        }
    }

    @Test
    public void testMergeIntoMapStoresExplicitNullValue() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("{\"a\":null}")) {
            p.nextToken(); // START_OBJECT
            Object result = deser.deserialize(p, null, map);

            assertSame(map, result);
            assertTrue(map.containsKey("a"));
            assertNull(map.get("a"));
        }
    }

    @Test
    public void testMergeStartingAtFieldNameToken() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("{\"a\":5,\"b\":6}")) {
            p.nextToken(); // START_OBJECT
            p.nextToken(); // FIELD_NAME: "a"
            Object result = deser.deserialize(p, null, map);

            assertSame(map, result);
            assertEquals(2, map.size());
            assertEquals(Integer.valueOf(5), map.get("a"));
            assertEquals(Integer.valueOf(6), map.get("b"));
        }
    }

    @Test
    public void testMergeIntoCollectionAppendsElements() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        List<Object> list = new ArrayList<>();
        list.add(1);

        try (JsonParser p = mapper.createParser("[2,\"three\",null]")) {
            p.nextToken(); // START_ARRAY
            Object result = deser.deserialize(p, null, list);

            assertSame(list, result);
            assertEquals(4, list.size());
            assertEquals(Integer.valueOf(1), list.get(0));
            assertEquals(Integer.valueOf(2), list.get(1));
            assertEquals("three", list.get(2));
            assertNull(list.get(3));
        }
    }

    @Test
    public void testEmptyArrayKeepsCollectionUnchanged() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        List<Object> list = new ArrayList<>();
        list.add("existing");

        try (JsonParser p = mapper.createParser("[]")) {
            p.nextToken(); // START_ARRAY
            Object result = deser.deserialize(p, null, list);

            assertSame(list, result);
            assertEquals(1, list.size());
            assertEquals("existing", list.get(0));
        }
    }

    @Test
    public void testEmptyObjectReturnsIntoValueUnchanged() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("{}")) {
            p.nextToken(); // START_OBJECT
            Object result = deser.deserialize(p, null, map);

            assertSame(map, result);
            assertEquals(1, map.size());
            assertEquals(Integer.valueOf(1), map.get("a"));
        }
    }

    @Test
    public void testEndObjectTokenReturnsIntoValue() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("{}")) {
            p.nextToken(); // START_OBJECT
            p.nextToken(); // END_OBJECT
            Object result = deser.deserialize(p, null, map);

            assertSame(map, result);
            assertEquals(1, map.size());
        }
    }

    @Test
    public void testEndArrayTokenReturnsIntoValue() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        List<Object> list = new ArrayList<>();
        list.add("keep");

        try (JsonParser p = mapper.createParser("[1]")) {
            p.nextToken(); // START_ARRAY
            p.nextToken(); // VALUE_NUMBER_INT
            p.nextToken(); // END_ARRAY
            Object result = deser.deserialize(p, null, list);

            assertSame(list, result);
            assertEquals(1, list.size());
            assertEquals("keep", list.get(0));
        }
    }

    @Test
    public void testScalarInputIgnoresIntoValue() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("42")) {
            p.nextToken(); // VALUE_NUMBER_INT
            Object result = deser.deserialize(p, null, map);

            assertEquals(Integer.valueOf(42), result);
            assertNotSame(map, result);
            assertEquals(1, map.size());
            assertEquals(Integer.valueOf(1), map.get("a"));
        }
    }

    @Test
    public void testNonMergingVariantIgnoresIntoValue() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR(true);
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("7")) {
            p.nextToken(); // VALUE_NUMBER_INT
            Object result = deser.deserialize(p, null, map);

            assertEquals(Integer.valueOf(7), result);
            assertNotSame(map, result);
            assertEquals(1, map.size());
            assertEquals(Integer.valueOf(1), map.get("a"));
        }
    }

    @Test
    public void testMalformedJsonDuringMergeThrowsJacksonException() throws Exception {
        UntypedObjectDeserializerNR deser = new UntypedObjectDeserializerNR();
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("a", 1);

        try (JsonParser p = mapper.createParser("{\"a\":}")) {
            p.nextToken(); // START_OBJECT
            try {
                deser.deserialize(p, null, map);
                fail("Expected an exception for malformed JSON content");
            } catch (JacksonException e) {
                // expected
            }
        }
    }
}