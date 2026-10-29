package tools.jackson.databind.deser.jdk;

import static org.junit.Assert.*;

import java.util.EnumMap;

import org.junit.Test;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

public class DeserializeTests {

    // Enum used for map keys
    enum Day { MON, TUE, WED }

    // Holder class to deserialize into
    static class Holder {
        public EnumMap<Day, Integer> map;
    }

    @Test
    public void testBasicEnumMapDeserialization() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        String json = "{\"map\":{\"MON\":1,\"TUE\":2}}";

        Holder h = mapper.readValue(json, Holder.class);

        assertNotNull("Deserialized map should not be null", h.map);
        assertEquals(Integer.valueOf(1), h.map.get(Day.MON));
        assertEquals(Integer.valueOf(2), h.map.get(Day.TUE));
        // WED should be absent
        assertFalse("Map should not contain WED key", h.map.containsKey(Day.WED));
    }

    @Test(expected = JacksonException.class)
    public void testUnknownEnumKeyThrowsByDefault() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        String json = "{\"map\":{\"MON\":1,\"X\":2}}";

        // This should throw because X is not a declared Day enum value
        mapper.readValue(json, Holder.class);
    }

    @Test
    public void testNullValueDeserialization() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        String json = "{\"map\":{\"MON\":null}}";

        Holder h = mapper.readValue(json, Holder.class);

        assertNotNull("Deserialized map should not be null", h.map);
        // Null values should be preserved as null entries in the map
        assertNull("Value for MON should be null", h.map.get(Day.MON));
    }

    @Test
    public void testEmptyEnumMapDeserialization() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        String json = "{\"map\":{}}";

        Holder h = mapper.readValue(json, Holder.class);

        assertNotNull("Deserialized map should not be null", h.map);
        assertTrue("Map should be empty", h.map.isEmpty());
    }
}