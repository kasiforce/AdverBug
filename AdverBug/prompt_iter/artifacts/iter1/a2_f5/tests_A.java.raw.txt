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

public class DeserializeTests {

    @Test
    public void testMergeScalarsIntoExistingMap() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("a", 42);
        m.put("b", "old");

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":43,\"c\":true}");

        assertSame(m, result);
        assertEquals(3, m.size());
        assertEquals(43, m.get("a"));
        assertEquals("old", m.get("b"));
        assertEquals(Boolean.TRUE, m.get("c"));
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testDeepMergeNestedMaps() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":{\"x\":1,\"y\":2}}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":{\"y\":9,\"z\":3}}");

        assertSame(m, result);
        assertEquals(1, m.size());
        Map<String, Object> a = (Map<String, Object>) m.get("a");
        assertEquals(3, a.size());
        assertEquals(1, a.get("x"));
        assertEquals(9, a.get("y"));
        assertEquals(3, a.get("z"));
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testRecursiveDeepMerge() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":{\"b\":{\"x\":1}}}", Map.class);

        mapper.readerForUpdating(m).readValue("{\"a\":{\"b\":{\"y\":2}}}");

        Map<String, Object> a = (Map<String, Object>) m.get("a");
        Map<String, Object> b = (Map<String, Object>) a.get("b");
        assertEquals(2, b.size());
        assertEquals(1, b.get("x"));
        assertEquals(2, b.get("y"));
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testMergeAppendsToExistingList() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":[1,2]}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":[3,4]}");

        assertSame(m, result);
        List<Object> list = (List<Object>) m.get("a");
        assertEquals(Arrays.asList(1, 2, 3, 4), list);
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testEmptyObjectAndArrayAreNoOps() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"obj\":{\"x\":1},\"arr\":[1]}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"obj\":{},\"arr\":[]}");

        assertSame(m, result);
        assertEquals(2, m.size());
        Map<String, Object> obj = (Map<String, Object>) m.get("obj");
        assertEquals(1, obj.size());
        assertEquals(1, obj.get("x"));
        List<Object> arr = (List<Object>) m.get("arr");
        assertEquals(Arrays.asList(1), arr);
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testEmptyObjectMergedIntoListIsNoOp() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":[9]}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":{}}");

        assertSame(m, result);
        List<Object> list = (List<Object>) m.get("a");
        assertEquals(Arrays.asList(9), list);
    }

    @Test
    public void testScalarReplacesExistingObjectValue() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":{\"x\":1}}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":42}");

        assertSame(m, result);
        assertEquals(42, m.get("a"));
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testArrayReplacesExistingMapValue() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":{\"x\":1}}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":[7,8]}");

        assertSame(m, result);
        List<Object> list = (List<Object>) m.get("a");
        assertEquals(Arrays.asList(7, 8), list);
    }

    @Test
    public void testNullReplacesExistingScalar() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":42}", Map.class);

        Object result = mapper.readerForUpdating(m).readValue("{\"a\":null}");

        assertSame(m, result);
        assertTrue(m.containsKey("a"));
        assertNull(m.get("a"));
    }

    @SuppressWarnings("unchecked")
    @Test
    public void testRepeatedMergeIsIdempotent() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":{\"x\":1}}", Map.class);
        String update = "{\"a\":{\"x\":5}}";

        mapper.readerForUpdating(m).readValue(update);
        mapper.readerForUpdating(m).readValue(update);

        Map<String, Object> a = (Map<String, Object>) m.get("a");
        assertEquals(1, a.size());
        assertEquals(5, a.get("x"));
    }

    @Test
    public void testUpdatingRootListAppendsElements() throws Exception {
        JsonMapper mapper = new JsonMapper();
        List<Object> list = new ArrayList<>(Arrays.asList(1, 2));

        Object result = mapper.readerForUpdating(list).readValue("[3,4]");

        assertSame(list, result);
        assertEquals(Arrays.asList(1, 2, 3, 4), list);
    }

    @Test(expected = JacksonException.class)
    public void testMalformedJsonThrowsException() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("a", 1);

        mapper.readerForUpdating(m).readValue("{\"a\": tru}");
    }

    @Test(expected = JacksonException.class)
    public void testUpdatingMapWithArrayTokenThrowsException() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("a", 1);

        mapper.readerForUpdating(m).readValue("[1,2]");
    }

    @Test(expected = JacksonException.class)
    public void testMergingNonEmptyObjectIntoListValueThrowsException() throws Exception {
        JsonMapper mapper = new JsonMapper();
        Map<String, Object> m = mapper.readValue("{\"a\":[9]}", Map.class);

        mapper.readerForUpdating(m).readValue("{\"a\":{\"k\":1}}");
    }
}