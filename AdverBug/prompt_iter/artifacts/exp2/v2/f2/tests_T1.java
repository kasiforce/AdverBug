package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import java.util.EnumMap;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JavaType;

public class DeserializeTests {

    private enum MyEnum { A, B }

    @Test
    public void testBasicDeserialization() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JavaType type = mapper.getTypeFactory()
                .constructMapType(EnumMap.class, MyEnum.class, String.class);

        String json = "{\"A\":\"one\",\"B\":\"two\"}";
        EnumMap<MyEnum, String> map = mapper.readValue(json, type);

        assertEquals("one", map.get(MyEnum.A));
        assertEquals("two", map.get(MyEnum.B));
        assertEquals(2, map.size());
    }

    @Test
    public void testNullValueDeserialization() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JavaType type = mapper.getTypeFactory()
                .constructMapType(EnumMap.class, MyEnum.class, String.class);

        String json = "{\"A\":null,\"B\":\"two\"}";
        EnumMap<MyEnum, String> map = mapper.readValue(json, type);

        assertNull(map.get(MyEnum.A));
        assertEquals("two", map.get(MyEnum.B));
        assertEquals(2, map.size());
    }

    @Test
    public void testUnknownEnumKeyThrowsByDefault() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JavaType type = mapper.getTypeFactory()
                .constructMapType(EnumMap.class, MyEnum.class, String.class);

        String json = "{\"C\":\"value\"}";
        try {
            mapper.readValue(json, type);
            fail("Expected exception due to unknown enum key");
        } catch (Exception e) {
            // expected
        }
    }

    @Test
    public void testRepeatedDeserializationDoesNotShareState() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JavaType type = mapper.getTypeFactory()
                .constructMapType(EnumMap.class, MyEnum.class, String.class);

        String json1 = "{\"A\":\"one\"}";
        String json2 = "{\"B\":\"two\"}";

        EnumMap<MyEnum, String> m1 = mapper.readValue(json1, type);
        EnumMap<MyEnum, String> m2 = mapper.readValue(json2, type);

        assertEquals("one", m1.get(MyEnum.A));
        assertNull(m1.get(MyEnum.B));

        assertEquals("two", m2.get(MyEnum.B));
        assertNull(m2.get(MyEnum.A));
    }

    @Test
    public void testEmptyObjectReturnsEmptyMap() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JavaType type = mapper.getTypeFactory()
                .constructMapType(EnumMap.class, MyEnum.class, String.class);

        String json = "{}";
        EnumMap<MyEnum, String> map = mapper.readValue(json, type);

        assertTrue(map.isEmpty());
    }
}