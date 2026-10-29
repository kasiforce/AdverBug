import java.lang.reflect.Constructor;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.core.JsonFactory;
import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.deser.jdk.UntypedObjectDeserializerNR;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Unit tests for the merging entry point
 * deserialize(JsonParser, DeserializationContext, Object) of
 * tools.jackson.databind.deser.jdk.UntypedObjectDeserializerNR.
 */
public class tests_B {

    private final UntypedObjectDeserializerNR mergingDeserializer = new UntypedObjectDeserializerNR();

    private JsonParser parserFor(String json) throws Exception {
        return new JsonFactory().createParser(json);
    }

    @Test
    public void mergedMapUpdatesExistingValuesAndKeepsOthers() throws Exception {
        Map<Object, Object> intoValue = new LinkedHashMap<Object, Object>();
        intoValue.put("a", 1);
        intoValue.put("s", "keep");
        intoValue.put("b", 2);

        JsonParser p = parserFor("{\"a\":10,\"s\":\"changed\"}");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            Object result = mergingDeserializer.deserialize(p, null, intoValue);
            assertSame(intoValue, result);
        } finally {
            p.close();
        }

        assertEquals(3, intoValue.size());
        assertEquals(10, ((Number) intoValue.get("a")).intValue());
        assertEquals("changed", intoValue.get("s"));
        assertEquals(2, ((Number) intoValue.get("b")).intValue());
    }

    @Test
    public void mergedMapAddsNewProperties() throws Exception {
        Map<Object, Object> intoValue = new LinkedHashMap<Object, Object>();
        intoValue.put("a", 1);

        JsonParser p = parserFor("{\"a\":10,\"b\":20}");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            Object result = mergingDeserializer.deserialize(p, null, intoValue);
            assertSame(intoValue, result);
            assertNull(p.nextToken());
        } finally {
            p.close();
        }

        assertEquals(2, intoValue.size());
        assertEquals(10, ((Number) intoValue.get("a")).intValue());
        assertEquals(20, ((Number) intoValue.get("b")).intValue());
    }

    @Test
    public void nestedMapsAreMergedInPlace() throws Exception {
        Map<Object, Object> inner = new LinkedHashMap<Object, Object>();
        inner.put("x", 1);
        inner.put("y", 2);
        Map<Object, Object> outer = new LinkedHashMap<Object, Object>();
        outer.put("cfg", inner);

        JsonParser p = parserFor("{\"cfg\":{\"x\":99,\"z\":3}}");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            Object result = mergingDeserializer.deserialize(p, null, outer);
            assertSame(outer, result);
            assertSame(inner, outer.get("cfg"));
        } finally {
            p.close();
        }

        assertEquals(3, inner.size());
        assertEquals(99, ((Number) inner.get("x")).intValue());
        assertEquals(2, ((Number) inner.get("y")).intValue());
        assertEquals(3, ((Number) inner.get("z")).intValue());
    }

    @Test
    public void mergedCollectionAppendsElements() throws Exception {
        List<Object> intoValue = new ArrayList<Object>();
        intoValue.add(1);
        intoValue.add(2);

        JsonParser p = parserFor("[3,null]");
        try {
            assertEquals(JsonToken.START_ARRAY, p.nextToken());
            Object result = mergingDeserializer.deserialize(p, null, intoValue);
            assertSame(intoValue, result);
        } finally {
            p.close();
        }

        assertEquals(4, intoValue.size());
        assertEquals(1, ((Number) intoValue.get(0)).intValue());
        assertEquals(2, ((Number) intoValue.get(1)).intValue());
        assertEquals(3, ((Number) intoValue.get(2)).intValue());
        assertNull(intoValue.get(3));
    }

    @Test
    public void emptyObjectAndArrayTokensLeaveTargetUnchanged() throws Exception {
        Map<Object, Object> map = new LinkedHashMap<Object, Object>();
        map.put("a", 1);
        List<Object> list = new ArrayList<Object>();
        list.add("x");

        JsonParser p = parserFor("{}");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            assertSame(map, mergingDeserializer.deserialize(p, null, map));
        } finally {
            p.close();
        }
        assertEquals(1, map.size());
        assertEquals(1, ((Number) map.get("a")).intValue());

        JsonParser p2 = parserFor("[]");
        try {
            assertEquals(JsonToken.START_ARRAY, p2.nextToken());
            assertSame(list, mergingDeserializer.deserialize(p2, null, list));
        } finally {
            p2.close();
        }
        assertEquals(1, list.size());
        assertEquals("x", list.get(0));
    }

    @Test
    public void endObjectAndEndArrayTokensReturnIntoValueAsIs() throws Exception {
        Map<Object, Object> map = new LinkedHashMap<Object, Object>();
        map.put("a", 1);
        List<Object> list = new ArrayList<Object>();
        list.add("x");

        JsonParser p = parserFor("{\"a\":1}");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            p.nextToken();
            p.nextToken();
            assertEquals(JsonToken.END_OBJECT, p.nextToken());
            assertSame(map, mergingDeserializer.deserialize(p, null, map));
        } finally {
            p.close();
        }
        assertEquals(1, map.size());
        assertEquals(1, ((Number) map.get("a")).intValue());

        JsonParser p2 = parserFor("[]");
        try {
            assertEquals(JsonToken.START_ARRAY, p2.nextToken());
            assertEquals(JsonToken.END_ARRAY, p2.nextToken());
            assertSame(list, mergingDeserializer.deserialize(p2, null, list));
        } finally {
            p2.close();
        }
        assertEquals(1, list.size());
        assertEquals("x", list.get(0));
    }

    @Test
    public void nonMergingDeserializerReturnsNewValueWithoutMutatingTarget() throws Exception {
        Constructor<?> ctor = UntypedObjectDeserializerNR.class.getDeclaredConstructor(boolean.class);
        ctor.setAccessible(true);
        UntypedObjectDeserializerNR nonMerging = (UntypedObjectDeserializerNR) ctor.newInstance(Boolean.TRUE);

        Map<Object, Object> intoValue = new LinkedHashMap<Object, Object>();
        intoValue.put("a", 1);

        JsonParser p = parserFor("{\"a\":2}");
        Object result;
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            result = nonMerging.deserialize(p, null, intoValue);
        } finally {
            p.close();
        }

        assertNotSame(intoValue, result);
        assertTrue(result instanceof Map);
        Map<?, ?> asMap = (Map<?, ?>) result;
        assertEquals(1, asMap.size());
        assertEquals(2, ((Number) asMap.get("a")).intValue());
        assertEquals(1, intoValue.size());
        assertEquals(1, ((Number) intoValue.get("a")).intValue());
    }

    @Test
    public void nonContainerIntoValueIsReplacedByDeserializedValue() throws Exception {
        JsonParser p = parserFor("\"new\"");
        try {
            assertEquals(JsonToken.VALUE_STRING, p.nextToken());
            Object result = mergingDeserializer.deserialize(p, null, "old");
            assertEquals("new", result);
        } finally {
            p.close();
        }
    }

    @Test
    public void nullIntoValueIsPopulatedByDefaultDeserialization() throws Exception {
        JsonParser p = parserFor("[1,\"two\",true]");
        try {
            assertEquals(JsonToken.START_ARRAY, p.nextToken());
            Object result = mergingDeserializer.deserialize(p, null, (Object) null);
            assertTrue(result instanceof List);
            List<?> asList = (List<?>) result;
            assertEquals(3, asList.size());
            assertEquals(1, ((Number) asList.get(0)).intValue());
            assertEquals("two", asList.get(1));
            assertEquals(Boolean.TRUE, asList.get(2));
        } finally {
            p.close();
        }
    }

    @Test
    public void newPropertyWithObjectValueIsAddedAsMap() throws Exception {
        Map<Object, Object> intoValue = new LinkedHashMap<Object, Object>();

        JsonParser p = parserFor("{\"n\":{\"k\":1}}");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            assertSame(intoValue, mergingDeserializer.deserialize(p, null, intoValue));
        } finally {
            p.close();
        }

        assertEquals(1, intoValue.size());
        Object added = intoValue.get("n");
        assertTrue(added instanceof Map);
        assertEquals(1, ((Map<?, ?>) added).size());
        assertEquals(1, ((Number) ((Map<?, ?>) added).get("k")).intValue());
    }

    @Test
    public void malformedJsonSurfacesAsJacksonException() throws Exception {
        Map<Object, Object> intoValue = new LinkedHashMap<Object, Object>();
        intoValue.put("a", 1);

        JsonParser p = parserFor("{\"a\":1");
        try {
            assertEquals(JsonToken.START_OBJECT, p.nextToken());
            try {
                mergingDeserializer.deserialize(p, null, intoValue);
                fail("Expected JacksonException for truncated JSON input");
            } catch (JacksonException expected) {
                // expected: malformed input surfaces as JacksonException
            }
        } finally {
            p.close();
        }
    }

    @Test
    public void mergingSameInputTwiceIsIdempotent() throws Exception {
        Map<Object, Object> intoValue = new LinkedHashMap<Object, Object>();
        intoValue.put("a", 1);

        for (int i = 0; i < 2; i++) {
            JsonParser p = parserFor("{\"a\":10}");
            try {
                assertEquals(JsonToken.START_OBJECT, p.nextToken());
                assertSame(intoValue, mergingDeserializer.deserialize(p, null, intoValue));
            } finally {
                p.close();
            }
        }

        assertEquals(1, intoValue.size());
        assertEquals(10, ((Number) intoValue.get("a")).intValue());
    }
}