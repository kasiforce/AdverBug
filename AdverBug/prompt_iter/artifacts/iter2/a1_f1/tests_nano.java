package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.type.TypeFactory;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JavaType;

import java.util.EnumMap;

import tools.jackson.core.JacksonException;

public class _deserializeUsingPropertiesTests {

    enum Color { RED, GREEN, BLUE; }

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    public void testBasicEnumMapDeserialization() throws Exception {
        String json = "{\"RED\":1,\"GREEN\":2,\"BLUE\":3}";
        JavaType mapType = mapper.getTypeFactory().constructMapType(EnumMap.class, Color.class, Integer.class);

        EnumMap<Color, Integer> map = mapper.readValue(json, mapType);

        assertNotNull(map);
        assertEquals(3, map.size());
        assertEquals(Integer.valueOf(1), map.get(Color.RED));
        assertEquals(Integer.valueOf(2), map.get(Color.GREEN));
        assertEquals(Integer.valueOf(3), map.get(Color.BLUE));
    }

    @Test(expected = JacksonException.class)
    public void testInvalidValueThrowsException() throws Exception {
        // Value cannot be deserialized into Integer
        String json = "{\"RED\":\"abc\"}";
        JavaType mapType = mapper.getTypeFactory().constructMapType(EnumMap.class, Color.class, Integer.class);

        mapper.readValue(json, mapType);
    }

    @Test
    public void testUnknownEnumKeyIsNullWhenEnabled() throws Exception {
        String json = "{\"RED\":1,\"PURPLE\":5}";
        ObjectMapper mapperWithFlag = JsonMapper.builder()
                .enable(tools.jackson.databind.cfg.EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)
                .build();
        JavaType mapType = mapperWithFlag.getTypeFactory().constructMapType(EnumMap.class, Color.class, Integer.class);
        EnumMap<Color, Integer> map = mapperWithFlag.readValue(json, mapType);

        // Expect only the known key to be deserialized
        assertNotNull(map);
        assertEquals(1, map.size());
        assertEquals(Integer.valueOf(1), map.get(Color.RED));
        assertFalse(map.containsKey(null)); // ensure no null-key inserted
    }
}