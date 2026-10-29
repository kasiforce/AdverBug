package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.*;

import java.util.EnumMap;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

public class DeserializeTests {

    enum MyEnum {
        RED, GREEN, BLUE
    }

    public static class Holder {
        public EnumMap<MyEnum, Integer> map;
    }

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    public void testBasicDeserialization() throws Exception {
        String json = "{\"map\": {\"RED\": 1, \"GREEN\": 2}}";
        Holder h = mapper.readValue(json, Holder.class);
        assertNotNull("Map should not be null", h.map);
        assertEquals(2, h.map.size());
        assertEquals(Integer.valueOf(1), h.map.get(MyEnum.RED));
        assertEquals(Integer.valueOf(2), h.map.get(MyEnum.GREEN));
    }

    @Test
    public void testEmptyDeserialization() throws Exception {
        String json = "{\"map\": {}}";
        Holder h = mapper.readValue(json, Holder.class);
        assertNotNull("Map should not be null", h.map);
        assertEquals(0, h.map.size());
    }

    @Test(expected = JacksonException.class)
    public void testUnknownEnumKeyThrows() throws Exception {
        String json = "{\"map\": {\"PURPLE\": 1}}";
        mapper.readValue(json, Holder.class);
    }

    @Test
    public void testNullValueDeserialization() throws Exception {
        String json = "{\"map\": {\"RED\": null}}";
        Holder h = mapper.readValue(json, Holder.class);
        assertNotNull("Map should not be null", h.map);
        assertTrue("Map should contain the RED key", h.map.containsKey(MyEnum.RED));
        assertNull("Value for RED should be null", h.map.get(MyEnum.RED));
    }

    @Test
    public void testResultIsEnumMapInstance() throws Exception {
        String json = "{\"map\": {\"BLUE\": 3}}";
        Holder h = mapper.readValue(json, Holder.class);
        assertNotNull("Map should not be null", h.map);
        assertEquals(EnumMap.class, h.map.getClass());
    }
}