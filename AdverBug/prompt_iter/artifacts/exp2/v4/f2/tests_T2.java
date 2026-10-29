package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import java.util.EnumMap;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.json.JsonMapper; // added import for JsonMapper

public class DeserializeTests {

    enum Day { MON, TUE, WED }

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    public void testSimpleEnumMapDeserialization() throws Exception {
        String json = "{\"MON\":\"one\",\"TUE\":\"two\"}";
        EnumMap<Day, String> result = mapper.readValue(json, new TypeReference<EnumMap<Day, String>>() {});
        assertNotNull(result);
        assertEquals(2, result.size());
        assertEquals("one", result.get(Day.MON));
        assertEquals("two", result.get(Day.TUE));
        assertFalse(result.containsKey(Day.WED));
    }

    @Test(expected = JacksonException.class)
    public void testUnknownEnumKeyThrows() throws Exception {
        String json = "{\"MOU\":\"x\"}";
        mapper.readValue(json, new TypeReference<EnumMap<Day, String>>() {});
    }

    @Test
    public void testUnknownEnumKeySkippedWhenConfigured() throws Exception {
        ObjectMapper m = JsonMapper.builder()
                .enable(tools.jackson.databind.cfg.EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        String json = "{\"MON\":\"one\",\"XERR\":\"ignore\"}";
        EnumMap<Day, String> result = m.readValue(json, new TypeReference<EnumMap<Day, String>>() {});
        assertNotNull(result);
        assertEquals(1, result.size());
        assertEquals("one", result.get(Day.MON));
        assertFalse(result.containsKey(Day.TUE));
    }

    @Test
    public void testNullValueDeserialization() throws Exception {
        String json = "{\"MON\":null}";
        EnumMap<Day, String> result = mapper.readValue(json, new TypeReference<EnumMap<Day, String>>() {});
        assertNotNull(result);
        assertEquals(1, result.size());
        assertNull(result.get(Day.MON));
    }

    @Test
    public void testEmptyObjectProducesEmptyEnumMap() throws Exception {
        String json = "{}";
        EnumMap<Day, String> result = mapper.readValue(json, new TypeReference<EnumMap<Day, String>>() {});
        assertNotNull(result);
        assertEquals(0, result.size());
    }
}