import org.junit.Test;
import static org.junit.Assert.*;

import java.util.EnumMap;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.type.TypeFactory;
import tools.jackson.databind.JavaType;

public class _deserializeUsingPropertiesTests {

    enum TestEnum { A, B, C }

    private final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void testSimpleEnumMapDeserialization() throws Exception {
        JavaType type = MAPPER.getTypeFactory().constructMapType(EnumMap.class, TestEnum.class, String.class);
        EnumMap<TestEnum, String> map = MAPPER.readValue("{\"A\":\"alpha\",\"B\":\"beta\"}", type);
        assertNotNull(map);
        assertEquals(2, map.size());
        assertEquals("alpha", map.get(TestEnum.A));
        assertEquals("beta", map.get(TestEnum.B));
        assertFalse(map.containsKey(TestEnum.C));
    }

    @Test
    public void testUnknownEnumKeyThrowsException() throws Exception {
        JavaType type = MAPPER.getTypeFactory().constructMapType(EnumMap.class, TestEnum.class, String.class);
        try {
            MAPPER.readValue("{\"Z\":\"value\"}", type);
            fail("Expected an exception due to unknown enum key");
        } catch (Exception e) {
            // Expecting a Jackson exception due to unknown enum key
            assertTrue(e.getClass().getName().contains("Exception"));
        }
    }
}